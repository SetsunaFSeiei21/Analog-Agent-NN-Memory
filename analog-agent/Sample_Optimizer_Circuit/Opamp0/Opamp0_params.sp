* ============================================================
* Opamp0_params.sp
*
* 25 design parameters for Opamp0: nine W/L groups, six M values,
* and one bias current. These are example values, not a golden point.
*
* Units:
*   W, L    -> um
*   IBIAS_A -> A
*   M       -> dimensionless positive integer
* ============================================================

.param DESVAR_W1=5.0
.param DESVAR_L1=0.5

.param DESVAR_W2=5.0
.param DESVAR_L2=0.5

.param DESVAR_W3=5.0
.param DESVAR_L3=0.5

.param DESVAR_W4=5.0
.param DESVAR_L4=0.5

.param DESVAR_W5=5.0
.param DESVAR_L5=0.5

.param DESVAR_W6=5.0
.param DESVAR_L6=0.5

.param DESVAR_W7=5.0
.param DESVAR_L7=0.5

.param DESVAR_W8=5.0
.param DESVAR_L8=0.5

.param DESVAR_W9=5.0
.param DESVAR_L9=0.5

* Tail PMOS, input pair, upper PMOS mirror, PMOS cascodes,
* NMOS sinks, and NMOS cascodes, respectively.
.param DESVAR_M1=2
.param DESVAR_M2=1
.param DESVAR_M3=1
.param DESVAR_M4=1
.param DESVAR_M5=2
.param DESVAR_M6=1

.param IBIAS_A=5e-6
