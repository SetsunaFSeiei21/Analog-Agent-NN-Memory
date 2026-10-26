* ============================================================
* load_to_114_params.sp
*
* W/L     : um, without a u suffix
* M       : dimensionless positive integer
* CCOMP_F : F
* IBIAS_A : A
*
* Initial sizing values, not sampling limits.
* Equal initial values do not bind independent parameters.
* ============================================================

* NMOS reference mirror: XNM1 / XNM7
.param DESVAR_W1=2
.param DESVAR_L1=1

* PMOS reference mirror: XPM5 / XPM17 / XPM18
.param DESVAR_W2=4
.param DESVAR_L2=1

* Tail reference, tail and output sink: XNM2 / XNM10 / XNM8
* W3/L3 remains independent of W1/L1.
.param DESVAR_W3=2
.param DESVAR_L3=1

* Matched input differential pair: XNM12 / XNM13
.param DESVAR_W4=8
.param DESVAR_L4=0.5

* Matched NMOS cascode pair: XNM11 / XNM9
.param DESVAR_W5=8
.param DESVAR_L5=0.5

* First-stage PMOS mirror load: XPM6 / XPM16
.param DESVAR_W6=4
.param DESVAR_L6=1

* PMOS second-stage device: XPM15
.param DESVAR_W7=8
.param DESVAR_L7=1

* Independent cascode-bias device: XNM4
.param DESVAR_W8=0.5
.param DESVAR_L8=1

* Input-stage multiplier; tail uses 1+2*M1.
.param DESVAR_M1=1

* Additional second-stage multiplier; output devices use M1*M2.
.param DESVAR_M2=4

* Cascode-bias device multiplier
.param DESVAR_M3=1

* Miller compensation: 1 pF
.param CCOMP_F=1e-12

* Reference current: 1 uA
.param IBIAS_A=1e-6