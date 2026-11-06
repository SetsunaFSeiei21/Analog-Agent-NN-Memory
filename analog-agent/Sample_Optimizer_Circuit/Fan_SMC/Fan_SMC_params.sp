* ============================================================
* Fan_SMC - original seven-group parameterization
*
* W/L: um with scale=1u
* C: F; I: A
*
* 23 independent parameters:
*   7 W + 7 L + 7 M + C + I
*
* Nominal DC/AC/follower transient checked:
*   ngspice 42, SkyWater LVT TT, 27 C
*   VDD=1.8 V, VCM=0.72 V, external CL=1 pF
* ============================================================

* PMOS bias mirror and first-stage mirror load
* Original MOSFET_0_8_*_BIASCM_PMOS
.param DESVAR_W1=4
.param DESVAR_L1=1
.param DESVAR_M1=1

* PMOS input differential pair
* Original MOSFET_8_2_*_gm1_PMOS
.param DESVAR_W2=8
.param DESVAR_L2=0.5
.param DESVAR_M2=1

* Second-stage PMOS transconductor
* Original MOSFET_10_1_*_gm2_PMOS
.param DESVAR_W3=8
.param DESVAR_L3=0.5
.param DESVAR_M3=1

* NMOS bias and folded-cascode network
* Original MOSFET_17_7_*_BIASCM_NMOS
.param DESVAR_W4=1
.param DESVAR_L4=1
.param DESVAR_M4=1

* Second-stage NMOS mirror
* Original MOSFET_21_2_*_LOAD2_NMOS
.param DESVAR_W5=4
.param DESVAR_L5=1
.param DESVAR_M5=1

* Output-stage NMOS
* Original MOSFET_23_1_*_gm3_NMOS
.param DESVAR_W6=8
.param DESVAR_L6=0.5
.param DESVAR_M6=10

* Feedforward PMOS
* Original MOSFET_11_1_*_gmf2_PMOS
.param DESVAR_W7=8
.param DESVAR_L7=0.5
.param DESVAR_M7=10

* Original CAPACITOR_0: NET50--VOUT
.param CCOMP_F=1e-12

* Original CURRENT_0_BIAS: NET13 -> VSS
.param IBIAS_A=1e-6