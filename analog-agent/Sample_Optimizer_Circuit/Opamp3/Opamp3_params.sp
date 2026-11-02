* ============================================================
* Opamp3 - initial design parameters
*
* 20 independent parameters:
*   8 W + 8 L + 3 M + IBIAS_A
*
* W/L: um under scale=1u.
* IBIAS_A: A per reference current source.
*
* Initial values are not a SPICE-verified operating point.
* Sampling ranges are defined in parameter_ranges.json.
* ============================================================

* PMOS IB2 reference/mirror: XPM11 / XPM10.
.param DESVAR_W1=4
.param DESVAR_L1=0.5

* NMOS input devices: XNM7 / XNM5.
.param DESVAR_W2=8
.param DESVAR_L2=0.5

* Lower PMOS output mirror: XPM2 / XPM3.
.param DESVAR_W3=8
.param DESVAR_L3=0.5

* Upper PMOS output mirror: XPM0 / XPM1.
.param DESVAR_W4=8
.param DESVAR_L4=0.5

* Upper NMOS output mirror: XNM12 / XNM13.
.param DESVAR_W5=8
.param DESVAR_L5=0.5

* Lower NMOS output mirror: XNM14 / XNM15.
.param DESVAR_W6=8
.param DESVAR_L6=0.5

* PMOS input devices: XPM8 / XPM7.
.param DESVAR_W7=4
.param DESVAR_L7=0.5

* NMOS IB1 reference/mirror: XNM_BIAS1_REF / XNM_BIAS1_OUT.
.param DESVAR_W8=8
.param DESVAR_L8=0.5

* XPM10 / XNM5 / XPM2 / XPM0.
.param DESVAR_M1=1

* XPM3 / XPM1 / XNM13 / XNM15.
.param DESVAR_M2=1

* XPM7 / XNM_BIAS1_OUT / XNM12 / XNM14.
.param DESVAR_M3=1

* Same magnitude for both reference currents: 1 uA each.
.param IBIAS_A=1e-6