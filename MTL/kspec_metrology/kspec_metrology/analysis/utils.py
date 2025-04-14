import numpy as np


def com(im_crop, x_crop, y_crop):
    xsum = np.sum(im_crop, axis=0)
    ysum = np.sum(im_crop, axis=1)

    xcom = np.sum( x_crop*xsum ) / np.sum(xsum)
    ycom = np.sum( y_crop*ysum ) / np.sum(ysum)

    return xcom, ycom


focal2camera_coeff = np.array([-1.18e-1, 0.
                            , -1e-4 , -1e-8 , -1e-10, -1e-13
                            ,  1e-7 ,  1e-11, -1e-1
                            , -1e-10, -1e-10,  1e-8 , -1e-8])

camera2focal_coeff = np.array([-8.5, 0. 
                            , 1e-6 , 1e-11,  1e-16, 1e-20
                            , 1e-8 , 1e-11, -1e-3 
                            , 1e-14, 1e-14, -1e-10, 1e-10])

def transform_polynomial(xin
               , m
               , theta
               , r1x, r2x, r3x, r4x
               , t1x, t2x, t3x
               , a1x, a2y, a4x, a3y
               ):
    
    xtemp, ytemp = xin
    xtemp = xtemp[:int(xtemp.size/2)]; ytemp = ytemp[:int(ytemp.size/2)]

    x = m*(xtemp*np.cos(theta)-ytemp*np.sin(theta))
    y = m*(xtemp*np.sin(theta)+ytemp*np.cos(theta))
    
    r = (x**2 + y**2)**0.5
    xrad_term = x*(r1x*(r**2) + r2x*(r**4) + r3x*(r**6) + r4x*(r**8) )
    xtan_term = (t1x*(r**2 + 2*(x**2)) + t2x*2.*x*y)*(1.+t3x*(r**2))

    xnew = (x + xrad_term + xtan_term
            + a1x*z20(x,y)
            + a4x*z10(x,y)            
            )

    yrad_term = y*(r1x*(r**2) + r2x*(r**4) + r3x*(r**6) + r4x*(r**8))
    ytan_term = (t2x*(r**2 + 2*(y**2)) + t1x*2.*x*y)*(1.+t3x*(r**2))

    ynew = (y + yrad_term + ytan_term
            + a2y*z21(x,y)
            + a3y*z9(x,y)
            )

    new = np.concatenate((xnew, ynew))

    return new

def transform(x, y, coeff):
    xin = np.concatenate((x, x))
    yin = np.concatenate((y, y))
    temp = transform_polynomial((xin, yin)
                        , *coeff
                        )

    xout, yout = temp[:int(temp.size/2)], temp[int(temp.size/2):]

    return xout, yout



def z2(x,y):
    return x

def z3(x,y):
    return y

def z4(x, y):
    return 2.*(x**2 + y**2) - 1.

def z5(x, y):
    return x*y

def z6(x, y):
    return (x**2 - y**2)

def z7(x,y):
    return y*(3.*(x**2 + y**2) - 2.)

def z8(x,y):
    return x*(3.*(x**2 + y**2) - 2.)

def z9(x,y):
    return y*(3.*(x**2) - y**2)

def z10(x,y):
    return  x*(x**2 - 3.*(y**2))

def z11(x,y):
    return 6.*( (x**2+y**2)**2 ) - 6.*(x**2+y**2) +1

def z12(x,y):
    return (x**2 - y**2)*(4.*(x**2+y**2) - 3.)

def z13(x,y):
    return x*y*(4.*(x**2+y**2) - 3.)

def z14(x,y):
    return (x**2+y**2)**2 - 8.*(x**2)*(y**2)

def z15(x,y):
    return x*y*(x**2 - y**2) 

def z16(x,y):
    return x*(10.*((x**2+y**2)**2) - 12.*(x**2+y**2) +3.)

def z17(x,y):
    return y*(10.*((x**2+y**2)**2) - 12.*(x**2+y**2) +3.)

def z18(x,y):
    return x*(x**2 - 3.*(y**2))*(5.*(x**2+y**2)-4.)

def z19(x,y):
    return y*(3.*(x**2) - y**2)*(5.*(x**2+y**2)-4.)

def z20(x,y):
    return x*(16.*(x**4) - 20.*(x**2)*(x**2+y**2) + 5.*((x**2+y**2)**2))

def z21(x,y):
    return y*(16.*(y**4) - 20.*(y**2)*(x**2+y**2) + 5.*((x**2+y**2)**2))