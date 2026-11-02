* ============================================================
* Opamp3 - complementary-input revision, Sky130 1.8-V LVT
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um under scale=1u.
* IBIAS_A: A per reference current source.
*
* 20 independent parameters:
*   8 W + 8 L + 3 M + IBIAS_A
*
* Original device-name mapping:
*   MNM7 -> XNM_BIAS1_REF
*   MNM8 -> XNM_BIAS1_OUT
*   Mxm7 -> XNM7
*
* NMOS bulks connect to VSS.
* PMOS bulks follow their respective sources.
* ============================================================

.include "Opamp3_params.sp"
.option scale=1u

.subckt DUT VINP VINN VOUT VDD VSS

* ------------------------------------------------------------
* Equal reference-current magnitudes.
* IB1: current injected into the NMOS reference diode.
* IB2: current drawn from the PMOS reference diode.
* ------------------------------------------------------------

IBIAS_SRC1 VDD IB1 DC {IBIAS_A}
IBIAS_SRC2 IB2 VSS DC {IBIAS_A}

* ------------------------------------------------------------
* IB2-controlled NMOS input path.
* Reference branch: 1.
* Signal branch: DESVAR_M1.
* ------------------------------------------------------------

XPM11 IB2   IB2  NET42 NET42 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM10 VSS   IB2  NET34 NET34 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}

XNM7  VDD   VINN NET42 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XNM5  NET24 VINP NET34 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M1}

* ------------------------------------------------------------
* PMOS output mirror.
* Reference branch: DESVAR_M1.
* Output branch: DESVAR_M2.
* ------------------------------------------------------------

XPM2 NET24 NET24 NET23 NET23 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1}
XPM3 VOUT  NET24 NET45 NET45 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M2}

XPM0 NET23 NET23 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XPM1 NET45 NET23 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M2}

* ------------------------------------------------------------
* NMOS output mirror.
* Reference branch: DESVAR_M3.
* Output branch: DESVAR_M2.
* ------------------------------------------------------------

XNM12 NET17 NET17 NET16 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M3}
XNM13 VOUT  NET17 NET44 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}

XNM14 NET16 NET16 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M3}
XNM15 NET44 NET16 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M2}

* ------------------------------------------------------------
* IB1-controlled PMOS input path.
* Reference branch: 1.
* Signal branch: DESVAR_M3.
*
* VINP rising reduces the NMOS output-mirror reference current.
* ------------------------------------------------------------

XPM8 VSS   VINN NET1 NET1 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m=1
XPM7 NET17 VINP NET2 NET2 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M3}

XNM_BIAS1_REF IB1 IB1 NET1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m=1
XNM_BIAS1_OUT VDD IB1 NET2 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M3}

.ends DUT