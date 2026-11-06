* Opamp5 nominal point: W/L in um (scale=1u), m dimensionless, C in F, I in A.
* Main amplifier: W1..W7, L1..L7, M1..M3 and CCOMP_F (18 parameters).
.param DESVAR_W1=2
.param DESVAR_L1=1
.param DESVAR_W2=2
.param DESVAR_L2=1
.param DESVAR_W3=2
.param DESVAR_L3=1
.param DESVAR_W4=5
.param DESVAR_L4=0.6
.param DESVAR_W5=2.15
.param DESVAR_L5=1
.param DESVAR_W6=1.35
.param DESVAR_L6=1
.param DESVAR_W7=1.57
.param DESVAR_L7=1
.param DESVAR_M1=2
.param DESVAR_M2=4
.param CCOMP_F=1.5e-12

* Auxiliary PMOS geometry (not used by the core).
.param DESVAR_W8=2
.param DESVAR_L8=1
* Shared by XPM0 / XNM5 / XNM4 and XPM_GMID_AUX. Keep M3 as a core feature.
.param DESVAR_M3=1
* Forced total current of the auxiliary diode only, in A.
.param IBIAS_A=2e-6