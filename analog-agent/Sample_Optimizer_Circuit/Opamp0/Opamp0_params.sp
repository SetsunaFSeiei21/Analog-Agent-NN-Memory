* ============================================================
* Opamp0_params.sp
*
* Units:
*   W, L    -> um (Sky130 scale=1u convention)
*   M       -> dimensionless
*   IBIAS_A -> A
*
* Example initial values; not simulation-validated.
* ============================================================

* PMOS bias mirror: XPM9, XPM8, XPM7, XPM6
.param DESVAR_W1 = 5.0
.param DESVAR_L1 = 1.0

* NMOS current sinks: XNM4, XNM3, XNM2
.param DESVAR_W2 = 5.0
.param DESVAR_L2 = 1.0

* NMOS bias generator: XNM6, XNM5
.param DESVAR_W3 = 5.0
.param DESVAR_L3 = 1.0

* PMOS input pair: XPM5, XPM4
.param DESVAR_W4 = 5.0
.param DESVAR_L4 = 1.0

* NMOS folded-cascode pair: XNM1, XNM0
.param DESVAR_W5 = 5.0
.param DESVAR_L5 = 1.0

* Lower PMOS mirror pair: XPM1, XPM0
.param DESVAR_W6 = 5.0
.param DESVAR_L6 = 1.0

* Upper PMOS mirror pair: XPM3, XPM2
.param DESVAR_W7 = 5.0
.param DESVAR_L7 = 1.0

* Independent multipliers
.param DESVAR_M0 = 1
.param DESVAR_M1 = 1
.param DESVAR_M2 = 1

* Reference bias current: 1 uA
.param IBIAS_A = 1e-6
