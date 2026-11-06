* Opamp7 starting parameters.
* W/L in um; IBIAS_A in A.
* 22 independent parameters: 9 W + 9 L + 3 M + IBIAS_A.
* Only M1, M5 and M6 are used.
* Sampling ranges are configured separately.

* NMOS reference mirror for VB1/VB2/NET2.
.param DESVAR_W1=2
.param DESVAR_L1=1

* PMOS VB1 diode and upper current-source pair.
.param DESVAR_W2=4
.param DESVAR_L2=1

* PMOS VB2 bias stack.
.param DESVAR_W3=2
.param DESVAR_L3=1

* PMOS NET6 reference and NET3 bias mirror.
.param DESVAR_W4=4
.param DESVAR_L4=1

* NMOS VB3 mirror, cascode-bias diode and cascode pair.
.param DESVAR_W5=4
.param DESVAR_L5=1

* NMOS tail-current reference and tail.
.param DESVAR_W6=10
.param DESVAR_L6=1

* NMOS input differential pair.
.param DESVAR_W7=8
.param DESVAR_L7=0.5

* Lower NMOS current-mirror pair.
.param DESVAR_W8=0.5
.param DESVAR_L8=1

* PMOS NET2/VB3 bias mirror and folded pair.
.param DESVAR_W9=4
.param DESVAR_L9=1

* Lower diode multiplicity in the PMOS VB2 stack.
* XPM_BIAS_VB1 and XPM14 both have fixed m=1.
.param DESVAR_M1=1

* Input pair multiplier; tail uses 2*M5.
.param DESVAR_M5=1

* Folded pair and NMOS output mirror multiplier.
* Upper PMOS current sources use M5+M6.
.param DESVAR_M6=4

* Reference current: 5 uA.
.param IBIAS_A=5e-6