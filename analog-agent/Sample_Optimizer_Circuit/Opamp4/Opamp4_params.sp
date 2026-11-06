* ============================================================
* Opamp4 parameters
*
* W/L: um under scale=1u.
* Current: A; capacitance: F; resistance: ohm.
* 18 independent parameters.
*
* Example initial values; not a verified operating point.
* ============================================================

* PMOS reference, bias branch and output current source.
* XPM0 / XPM1 / XPM3
.param DESVAR_W1=4
.param DESVAR_L1=1

* NMOS reference and tail-current mirror.
* XNM7 / XNM8
.param DESVAR_W2=2
.param DESVAR_L2=1

* Matched NMOS input pair.
* XNM5 / XNM6
.param DESVAR_W3=8
.param DESVAR_L3=0.5

* First-stage PMOS current-mirror load.
* XPM9 / XPM10
.param DESVAR_W4=4
.param DESVAR_L4=1

* Additional PMOS branch-current sources.
* XPM4 / XPM5; independent of W1/L1.
.param DESVAR_W5=2
.param DESVAR_L5=1

* NMOS second-stage device.
* XNM11
.param DESVAR_W6=2
.param DESVAR_L6=1

* Multiplicity variables.
* Composite expressions remain in Opamp4.sp.
.param DESVAR_M1=1
.param DESVAR_M2=1
.param DESVAR_M3=1

* Reference current: 1 uA.
.param IBIAS_A=1e-6

* Compensation capacitor: 1 pF.
.param CCOMP_F=1e-12

* Series compensation resistor: 1 kohm.
.param RNULL_OHM=1000