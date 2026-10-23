* ============================================================
* Opamp116_params.sp
*
* W/L     : um
* M       : dimensionless positive integer
* IBIAS_A : A
*
* Parameter indices follow the original SimpleOpAmp116 names.
* Shared parameters are referenced directly in Opamp116.sp.
* ============================================================

* DiodeTransistorNmos1 -> XNM0
.param DESVAR_W1=26
.param DESVAR_L1=5
.param DESVAR_M1=1

* DiodeTransistorNmos2 -> XNM1
.param DESVAR_W2=534
.param DESVAR_L2=5
.param DESVAR_M2=1

* DiodeTransistorNmos3 -> XNM3
.param DESVAR_W3=51
.param DESVAR_L3=4
.param DESVAR_M3=1

* DiodeTransistorPmos4 -> XPM0
.param DESVAR_W4=20
.param DESVAR_L4=7
.param DESVAR_M4=1

* DiodeTransistorPmos5 -> XPM1
.param DESVAR_W5=376
.param DESVAR_L5=3
.param DESVAR_M5=1

* NormalTransistorNmos6 -> XNM2
* L shares DESVAR_L2.
.param DESVAR_W6=18
.param DESVAR_M6=1

* NormalTransistorNmos7/9 -> XNM5/XNM7
* Matched cascode pair.
.param DESVAR_W7=112
.param DESVAR_L7=4
.param DESVAR_M7=1

* NormalTransistorNmos8 -> XNM6
* W shares DESVAR_W2; L shares DESVAR_L1.
.param DESVAR_M8=1

* NormalTransistorNmos10/11 -> XNM8/XNM9
* Matched input pair.
.param DESVAR_W10=112
.param DESVAR_L10=4
.param DESVAR_M10=1

* NormalTransistorNmos12 -> XNM10
* W shares DESVAR_W1; L shares DESVAR_L2.
.param DESVAR_M12=1

* NormalTransistorPmos13 -> XPM2
.param DESVAR_W13=138
.param DESVAR_L13=10
.param DESVAR_M13=1

* NormalTransistorPmos14 -> XPM3
* L shares DESVAR_L4.
.param DESVAR_W14=275
.param DESVAR_M14=1

* NormalTransistorPmos15 -> XPM4
* L shares DESVAR_L5.
* W15 and W5 are independent, as in the original parameters.
.param DESVAR_W15=376
.param DESVAR_M15=1

* Example reference current; replace with the original TB value.
.param IBIAS_A=1e-6