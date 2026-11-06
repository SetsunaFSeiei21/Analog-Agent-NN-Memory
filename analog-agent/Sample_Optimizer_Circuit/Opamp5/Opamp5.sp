* Opamp5 / opamp5_33 -- SKY130 1.8 V LVT, W/L in um with scale=1u.
* 12 amplifier MOS + 1 auxiliary PMOS. VINP/VINN follow measured gain polarity.
.include "Opamp5_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Self-bias branch: VDD -> XPM0 -> XNM5 -> XNM4 -> VSS. All three use M3.
XPM0  NET9  NET9  VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={DESVAR_M3}
XNM5  NET9  NET9  NET8  VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={DESVAR_M3}
XNM4  NET8  NET8  VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M3}

* Tail and differential pair. The gate on the NET20 branch is noninverting.
XNM9  NET18 NET8  VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={2*DESVAR_M1}
XNM7  NET20 VINP  NET18 VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XNM8  NET32 VINN  NET18 VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}

* Common-gate devices: keep B=S as in the supplied opamp5_33 variant.
XPM4  NET32 NET8  NET19 NET19 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M1}
XPM5  NET20 NET8  NET21 NET21 sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M1}
XPM1  NET19 NET19 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M1}
XPM2  NET21 NET19 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={DESVAR_M1}

* Output pull-up senses NET21; the compensation capacitor returns to NET20.
XPM3  VOUT  NET21 VDD   VDD   sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W7} L={DESVAR_L7} m={DESVAR_M1*DESVAR_M2}
XNM11 VOUT  NET8  VSS   VSS   sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1*DESVAR_M2}
CC0   NET20 VOUT  {CCOMP_F}

* Auxiliary PMOS (schematic MPM5): separate W8/L8, M3 shared with the self-bias string.
* NET1 is local to the auxiliary PMOS and its ideal current source.
* The ideal source draws current out of NET1 and returns it to the same VDD.
XPM_GMID_AUX NET1 NET1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W8} L={DESVAR_L8} m={DESVAR_M3}
I_GMID_AUX   NET1 VDD DC {IBIAS_A}

.ends DUT