* ============================================================
* loOpamp116_params.sp
*
* W/L     : um
* M       : dimensionless positive integer
* IBIAS_A : A
*
* 21 independent parameters: 8 W + 8 L + 4 M + IBIAS_A.
* These are illustrative initial values, not sampling bounds or a verified OP.
* W/L are numbered by the new functional groups, not the old device numbers.
* L1 and L2 remain independent despite having equal initial values.
* ============================================================

* Upper NMOS bias devices: XNM0/XNM6 share W1/L1.
.param DESVAR_W1=26
.param DESVAR_L1=5

* Lower NMOS bias devices: XNM10/XNM1/XNM2 share W2/L2.
.param DESVAR_W2=534
.param DESVAR_L2=5

* Matched input differential pair: XNM8/XNM9.
.param DESVAR_W3=112
.param DESVAR_L3=4

* NMOS cascode bias: XNM3.
.param DESVAR_W4=51
.param DESVAR_L4=4

* Matched NMOS cascode pair: XNM7/XNM5.
.param DESVAR_W5=112
.param DESVAR_L5=4

* PMOS bias mirror: XPM0/XPM3.
.param DESVAR_W6=20
.param DESVAR_L6=7

* Matched PMOS active-load devices: XPM1/XPM4.
.param DESVAR_W7=376
.param DESVAR_L7=3

* PMOS output device: XPM2; M shares DESVAR_M3.
.param DESVAR_W8=138
.param DESVAR_L8=10

* Reference stack multiplier: XNM0/XNM10.
.param DESVAR_M1=1

* Bias-mirror reference branch: XNM2/XPM0.
.param DESVAR_M2=1

* Input, cascode and active-load branch multiplier.
.param DESVAR_M3=1

* Cascode-bias branch multiplier: XPM3/XNM3.
.param DESVAR_M4=1

* XNM1/XNM6 use the derived expression 2*M3+M4 in the main netlist.
* Example reference current, in amperes.
.param IBIAS_A=1e-6
