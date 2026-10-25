"""Call .NET members (the LightField Automation API) without holding the Python GIL.

LightField's own threads resolve assemblies through pythonnet's AssemblyResolve handler, which
takes the GIL. A .NET call that waits for such a thread while its Python caller holds the GIL
deadlocks: ``Automation(True, List[String]())`` never returned when called from Python, on the
main thread or an STA thread (LightField 6.15.2, pythonnet 3.2.1, 2026-10-24), and returned in
11-24 s through ``new`` below.

Each call is compiled into a .NET delegate (an expression tree, so no Python code runs on the
.NET side) and run on a short-lived STA thread, while the Python caller waits with time.sleep,
which releases the GIL. A .NET exception comes back as NetError. Calls are not serialised here.
"""

import time

POLL_S = 0.002


class NetError(RuntimeError):
    """A .NET exception raised by a call made through this module."""


def _expr():
    import clr

    clr.AddReference("System.Core")
    from System.Linq.Expressions import Expression

    return Expression


def _exprs(*items):
    """.NET Expression[] (pythonnet does not turn a list into one)."""
    from System import Array

    Expression = _expr()
    return Array[Expression](list(items))


def _net(value):
    """A Python int or float as a .NET value: pythonnet 3 passes them to an ``object``
    parameter (Expression.Constant) as PyInt/PyFloat, which no .NET type converts from."""
    from System import Double, Int32, Int64

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return Int32(value) if -2**31 <= value < 2**31 else Int64(value)
    if isinstance(value, float):
        return Double(value)
    return value


def _arg(Expression, value, param_type):
    """Constant expression for ``value``, converted to the parameter type when needed."""
    if value is None:
        return Expression.Constant(None, param_type)
    c = Expression.Constant(_net(value))
    return c if c.Type == param_type else Expression.Convert(c, param_type)


def _run(make_call):
    """Run the expression ``make_call(Expression)`` on an STA thread; return its value."""
    import clr
    from System import Exception as NetException
    from System import Object, Type
    from System.Runtime.CompilerServices import StrongBox
    from System.Threading import ApartmentState, Thread, ThreadStart

    Expression = _expr()
    void = Type.GetType("System.Void")
    value, error = StrongBox[Object](), StrongBox[NetException]()
    call = make_call(Expression)
    if call.Type != void:
        call = Expression.Assign(Expression.Field(Expression.Constant(value), "Value"),
                                 Expression.Convert(call, clr.GetClrType(Object)))
    ex = Expression.Parameter(clr.GetClrType(NetException), "ex")
    caught = Expression.Assign(Expression.Field(Expression.Constant(error), "Value"), ex)
    body = Expression.TryCatch(Expression.Block(void, _exprs(call)),
                               Expression.Catch(ex, Expression.Block(void, _exprs(caught))))
    thread = Thread(Expression.Lambda[ThreadStart](body).Compile())
    thread.IsBackground = True
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    while thread.IsAlive:
        time.sleep(POLL_S)
    if error.Value is not None:
        raise NetError(f"{error.Value.GetType().Name}: {error.Value.Message}")
    return value.Value


def new(net_type, *args):
    """``net_type(*args)`` (the constructor with that many parameters)."""
    import clr

    def make(Expression):
        t = clr.GetClrType(net_type)
        for ctor in t.GetConstructors():
            params = list(ctor.GetParameters())
            if len(params) == len(args):
                return Expression.New(ctor, _exprs(*[_arg(Expression, a, p.ParameterType)
                                                    for a, p in zip(args, params)]))
        raise NetError(f"{t.FullName} has no constructor with {len(args)} arguments")

    return _run(make)


def call(target, name, *args):
    """``target.name(*args)``: a public method of the object's class or of an interface it
    implements, chosen by name and number of arguments."""

    def make(Expression):
        obj = Expression.Constant(target)
        t = obj.Type
        for owner in [t, *t.GetInterfaces()]:
            for m in owner.GetMethods():
                params = list(m.GetParameters())
                if m.Name == name and len(params) == len(args):
                    return Expression.Call(obj, m, _exprs(*[_arg(Expression, a, p.ParameterType)
                                                           for a, p in zip(args, params)]))
        raise NetError(f"{t.FullName} has no method {name} with {len(args)} arguments")

    return _run(make)


def get(target, name):
    """The property ``target.name``."""
    return call(target, "get_" + name)


def items(collection):
    """The elements of a .NET list, read through its Count and indexer."""
    return [call(collection, "get_Item", i) for i in range(get(collection, "Count"))]
