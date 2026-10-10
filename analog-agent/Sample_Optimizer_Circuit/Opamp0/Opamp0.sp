* ============================================================
* opamp0 - Sky130 1.8-V operational amplifier
*
* Standard interface:
* .subckt DUT VINP VINN VOUT VDD VSS
*
* W and L are in um under the Sky130 scale=1u convention.
* ============================================================

.include "Opamp0_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

XPM9 VB2 NET1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM8 VB3 NET1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM7 NET1 NET1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM6 NET9 NET1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={2*DESVAR_M1}
XPM5 NET27 VINN NET9 NET9 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XPM4 NET24 VINP NET9 NET9 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XPM3 NET35 NET18 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M2}
XPM2 NET18 NET18 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M2}
XPM1 NET34 NET34 NET18 NET18 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M2}
XPM0 VOUT NET34 NET35 NET35 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M2}

XNM6 NET2 VB2 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m=1
XNM5 VB2 VB2 NET2 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M0}
XNM4 VB3 VB3 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XNM3 NET24 VB3 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M1+DESVAR_M2}
XNM2 NET27 VB3 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M1+DESVAR_M2}
XNM1 NET34 VB2 NET24 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}
XNM0 VOUT VB2 NET27 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}

IBIAS_SRC NET1 VSS DC {IBIAS_A}

.ends DUT
