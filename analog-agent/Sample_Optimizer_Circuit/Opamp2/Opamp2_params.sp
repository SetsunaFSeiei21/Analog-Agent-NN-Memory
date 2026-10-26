* Opamp2: 17 independent parameters.
* W/L are in um; IBIAS_A is in A.
* Illustrative initial values, not a verified operating point or sampling bounds.

* PMOS bias mirrors.
.param DESVAR_W1=4
.param DESVAR_L1=0.5

* NMOS cascode-bias generator.
.param DESVAR_W2=1
.param DESVAR_L2=0.5

* NMOS tail-current mirror.
.param DESVAR_W3=2
.param DESVAR_L3=0.5

* Matched input pair.
.param DESVAR_W4=6
.param DESVAR_L4=0.5

* Matched NMOS cascode pair.
.param DESVAR_W5=3
.param DESVAR_L5=0.5

* Lower PMOS mirror pair.
.param DESVAR_W6=6
.param DESVAR_L6=0.5

* Upper PMOS mirror pair.
.param DESVAR_W7=4
.param DESVAR_L7=0.5

.param DESVAR_M1=1
.param DESVAR_M2=1
.param IBIAS_A=1e-6
