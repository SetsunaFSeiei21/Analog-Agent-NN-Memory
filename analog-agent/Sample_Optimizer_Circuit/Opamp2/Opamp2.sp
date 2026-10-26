* ============================================================
* Opamp2 - Sky130 1.8-V LVT operational amplifier
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um; IBIAS_A: A.
* 17 independent parameters: 7 W + 7 L + 2 M + IBIAS_A.
* Device numbers follow the original opamp2 netlist.
* ============================================================

.include "Opamp2_params.sp"
.option scale=1u

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current drawn from the PMOS diode branch.
IBIAS_SRC NET6 VSS DC {IBIAS_A}

* PMOS reference and bias mirrors.
XPM6 NET6 NET6 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM5 VB1  NET6 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM4 NET3 NET6 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1

* NMOS cascode-bias generator; the lower device may be in triode.
XNM8 VB1  VB1 NET5 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M1}
XNM7 NET5 VB1 VSS  VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1

* Tail-current mirror: XNM4 shares W3/L3 with XNM5.
XNM5 NET3 NET3 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m=1
XNM4 NET1 NET3 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={2*DESVAR_M2}

* Matched NMOS differential input pair.
XNM0 NET16 VINP NET1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M2}
XNM1 NET18 VINN NET1 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M2}

* Matched NMOS cascode pair.
XNM3 NET4 VB1 NET16 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}
XNM2 VOUT VB1 NET18 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}

* Lower PMOS mirror pair; bulk follows each source.
XPM3 NET4 NET4 NET19 NET19 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M2}
XPM0 VOUT NET4 NET2  NET2  sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M2}

* Upper PMOS mirror pair.
XPM1 NET19 NET19 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M2}
XPM2 NET2  NET19 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M2}

.ends DUT
