# tests/test_init.py
import pytest
import kspec_gfa_controller as pkg


def test_dunder_all_exports_expected_names():
    assert set(pkg.__all__) == {"GFAActions", "GFAEnvironment", "GFAGuider"}


@pytest.mark.parametrize("name", ["GFAActions", "GFAEnvironment", "GFAGuider"])
def test_getattr_lazy_import_returns_type(name):
    """
    다른 테스트에서 sys.modules/monkeypatch로 실제 클래스가 Fake로 치환될 수 있으므로,
    여기서는 '요청한 이름이 타입(클래스)로 resolve된다'만 검증한다.
    """
    obj = getattr(pkg, name)
    assert isinstance(obj, type)


def test_getattr_unknown_raises_attribute_error():
    with pytest.raises(AttributeError):
        getattr(pkg, "DoesNotExist")


def test_from_import_triggers_lazy_getattr():
    # from-import가 __getattr__를 통해 resolve되는지만 확인
    from kspec_gfa_controller import GFAActions  # noqa: F401

    assert isinstance(GFAActions, type)
