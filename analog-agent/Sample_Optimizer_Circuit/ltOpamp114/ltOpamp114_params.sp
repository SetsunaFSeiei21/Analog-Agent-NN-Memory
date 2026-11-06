* ltOpamp114 - independent cascode-bias revision.
* 23 independent parameters: 9 W + 9 L + 3 M + CCOMP_F + IBIAS_A.
* W/L in um; M dimensionless; capacitance in F; current in A.

* NMOS reference: XNM1 / XNM7.
.param DESVAR_W1=2
.param DESVAR_L1=1

* PMOS reference: XPM5 / XPM17 / XPM18.
.param DESVAR_W2=4
.param DESVAR_L2=1

* Tail reference, tail and output sink: XNM2 / XNM10 / XNM8.
.param DESVAR_W3=2
.param DESVAR_L3=1

* Input pair: XNM12 / XNM13.
.param DESVAR_W4=8
.param DESVAR_L4=0.5

* Cascode pair: XNM11 / XNM9.
.param DESVAR_W5=8
.param DESVAR_L5=0.5

* First-stage PMOS mirror: XPM6 / XPM16.
.param DESVAR_W6=4
.param DESVAR_L6=1

* PMOS second stage: XPM15.
.param DESVAR_W7=8
.param DESVAR_L7=1

* Upper cascode-bias diode: XNM11_BIAS, fixed m=1.
.param DESVAR_W8=0.5
.param DESVAR_L8=1

* Lower cascode-bias pair: XNM12_BIAS / XNM13_BIAS.
.param DESVAR_W9=2
.param DESVAR_L9=1

* First-stage multiplier; the tail uses 2*M1.
.param DESVAR_M1=1

* Second-stage multiplier; the output devices use M1*M2.
.param DESVAR_M2=4

* XNM12_BIAS multiplicity; XNM13_BIAS remains m=1.
.param DESVAR_M3=1

* Nominal compensation: 3 pF.
.param CCOMP_F=3e-12

* Reference current: 1 uA.
.param IBIAS_A=1e-6