* ============================================================
* Opamp7 - NMOS-input folded-cascode OTA, SKY130 1.8 V LVT.
*
* Interface: DUT VINP VINN VOUT VDD VSS.
* W/L in um under scale=1u.
*
* Original vinn -> VINP; original vinp -> VINN.
*
* 26 MOS; 22 independent parameters:
*   9 W + 9 L + 3 M + IBIAS_A
*
* M1: PMOS VB2 cascode-bias diode multiplier.
* M5: input pair multiplier; tail uses 2*M5.
* M6: folded pair and NMOS output mirror multiplier.
* Upper PMOS current sources use M5+M6.
* ============================================================

.include "Opamp7_params.sp"
.option scale=1u

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current and NMOS bias mirror.
IBIAS_SRC VDD NET4 DC {IBIAS_A}

XNM_BIAS_REF  NET4 NET4 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM_BIAS_VB1  VB1  NET4 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM_BIAS_VB2  VB2  NET4 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM_BIAS_NET2 NET2 NET4 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1

* PMOS source-current and cascode biases.
XPM_BIAS_VB1        VB1  VB1 VDD  VDD  sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XPM_BIAS_CAS_SOURCE NET5 VB2 VDD  VDD  sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m=1
XPM_BIAS_CAS_DIODE  VB2  VB2 NET5 NET5 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1}

* Reference-driven VB3 bias.
* W9/L9 is shared with the PMOS folded pair.
XPM_BIAS_REF NET2 NET2 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m=1
XPM_BIAS_VB3 VB3  NET2 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m=1

XPM19 NET6 NET6 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m=1
XNM2  NET6 VB3  VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m=1
XNM17 VB3  VB3  VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m=1

* NMOS cascode and tail-current bias branch.
* All three devices below have fixed m=1.
XPM14 NET3 NET6 VDD  VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m=1
XNM15 NET3 NET3 NET1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m=1
XNM13 NET1 NET1 VSS  VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m=1

* Input tail and matched differential pair.
XNM4 NET10 NET1 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={2*DESVAR_M5}
XNM0 NET26 VINP NET10 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M5}
XNM3 NET32 VINN NET10 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M5}

* Matched PMOS current sources.
XPM16 NET26 VB1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M5+DESVAR_M6}
XPM18 NET32 VB1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M5+DESVAR_M6}

* Matched PMOS folded pair.
* Preserve source-connected bulk terminals.
XPM6 NET12 VB2 NET26 NET26 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m={DESVAR_M6}
XPM5 VOUT  VB2 NET32 NET32 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m={DESVAR_M6}

* NMOS cascode current-mirror load.
XNM8  NET12 NET3  NET27 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M6}
XNM7  VOUT  NET3  NET21 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M6}
XNM10 NET27 NET12 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M6}
XNM9  NET21 NET12 VSS   VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M6}

.ends DUT