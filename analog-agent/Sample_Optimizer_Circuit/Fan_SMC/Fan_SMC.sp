* ============================================================
* Fan_SMC - Sky130 1.8-V operational amplifier, LVT models
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um under the Sky130 scale=1u convention.
*
* 24 MOS; 23 independent parameters:
*   7 W + 7 L + 7 M + C + I
*
* Original connections and multiplicity factors are preserved.
* ============================================================

.include "Fan_SMC_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current
IBIAS_SRC NET13 VSS DC {IBIAS_A}

* ------------------------------------------------------------
* Group 1: PMOS bias mirror and first-stage mirror load
* ------------------------------------------------------------

XPM7 NET49 NET13 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}

XPM6 NET50 VOUTN VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}
XPM5 VOUTN VOUTN VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}

XPM4 NET31 NET13 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={4*DESVAR_M1}

XPM3 VB3   NET13 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}
XPM2 DM_1  NET13 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}
XPM1 VB4   NET13 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}
XPM0 NET13 NET13 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M1}

* ------------------------------------------------------------
* Group 2: matched PMOS input differential pair
* ------------------------------------------------------------

XPM9 NET63 VINP NET31 NET31 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M2}
XPM8 DM_2  VINN NET31 NET31 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M2}

* ------------------------------------------------------------
* Group 3: second-stage PMOS transconductor
* ------------------------------------------------------------

XPM10 NET43 NET50 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M3}

* ------------------------------------------------------------
* Group 4: NMOS bias and folded-cascode network
* ------------------------------------------------------------

XNM19 DM_2  VB4 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={8*DESVAR_M4}
XNM15 VOUTN VB3 DM_2  VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={4*DESVAR_M4}

XNM20 NET63 VB4 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={8*DESVAR_M4}
XNM16 NET50 VB3 NET63 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={4*DESVAR_M4}

XNM17 NET54 VB4 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={4*DESVAR_M4}
XNM14 VB3   VB3 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M4}
XNM12 VB4   VB3 NET54 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={4*DESVAR_M4}

XNM18 NET56 VB4 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={4*DESVAR_M4}
XNM13 DM_1  VB3 NET56 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={4*DESVAR_M4}

* ------------------------------------------------------------
* Group 5: second-stage NMOS mirror
* ------------------------------------------------------------

XNM22 NET49 NET43 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M5}
XNM21 NET43 NET43 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M5}

* ------------------------------------------------------------
* Group 6: output-stage NMOS
* ------------------------------------------------------------

XNM23 VOUT NET49 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M6}

* ------------------------------------------------------------
* Group 7: feedforward PMOS
* Gate driven by the first-stage output NET50.
* ------------------------------------------------------------

XPM11 VOUT NET50 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M7}

* Single compensation capacitor
CC0 NET50 VOUT {CCOMP_F}

.ends DUT