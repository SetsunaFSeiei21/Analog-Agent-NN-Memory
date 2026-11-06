* Opamp6 / opamp6_38 - SKY130 1.8 V LVT; W and L in um.
.include "Opamp6_params.sp"
.option scale=1u

.subckt DUT VINP VINN VOUT VDD VSS

* Bias devices from MNM*/MPM* use _BIAS; Mxm* keep their original index.
IBIAS_SRC VDD VB1 DC {IBIAS_A}
XNM7_BIAS  VB1   VB1   VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM8_BIAS  NET3  VB1   VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM10      NET35 VB1   VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M3}

* NMOS cascode gate bias at NET26.
XPM7_BIAS  NET3  NET3  VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1
XPM8_BIAS  NET26 NET3  VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M1}
XNM10_BIAS NET4  NET26 VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m=1
XNM9_BIAS  NET26 NET26 NET4  VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1*DESVAR_M2}

* PMOS cascode gate bias at NET35.
XPM6_BIAS  NET1  NET35 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m=1
XPM5_BIAS  NET35 NET35 NET1  NET1  sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M3*DESVAR_M4}

* Tail, input pair and diode-connected PMOS loads.
XNM9       NET17 VB1   VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={2*DESVAR_M5}
XNM7       NET11 VINN  NET17 VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={2*DESVAR_M5}
XNM8       NET21 VINP  NET17 VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={2*DESVAR_M5}
XPM1       NET11 NET11 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={2*DESVAR_M5}
XPM2       NET21 NET21 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={2*DESVAR_M5}

* Mirror and cascoded output branches.
XPM0       NET8  NET11 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M6}
XNM14      NET8  NET8  VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M6}
XNM13      NET38 NET8  VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M6}
XNM12      VOUT  NET26 NET38 VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M6}
XPM3       NET40 NET21 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M6}
XPM6       VOUT  NET35 NET40 NET40 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W9} L={DESVAR_L9} m={DESVAR_M6}

.ends DUT