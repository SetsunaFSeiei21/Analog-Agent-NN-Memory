* ============================================================
* Opamp4 - Sky130 1.8-V two-stage operational amplifier
*
* Interface: DUT VINP VINN VOUT VDD VSS
* W/L: um under scale=1u.
* Current: A; capacitance: F; resistance: ohm.
*
* 18 independent parameters:
*   6 W + 6 L + 3 M + IBIAS_A + CCOMP_F + RNULL_OHM
*
* Original connections and parameter sharing are preserved.
* W5/L5 remain independent of W1/L1.
* NMOS bulks: VSS. PMOS bulks: VDD.
* ============================================================

.include "Opamp4_params.sp"
.option scale=1u

.subckt DUT VINP VINN VOUT VDD VSS

* Reference current drawn from the PMOS diode branch.
IBIAS_SRC IB1 VSS DC {IBIAS_A}

* PMOS reference and NMOS bias-generation branch.
XPM0 IB1   IB1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XPM1 NET11 IB1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m=1
XNM7 NET11 NET11 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m=1

* Tail-current mirror.
XNM8 NET21 NET11 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W2} L={DESVAR_L2} m={2*(DESVAR_M1+DESVAR_M2)}

* Matched NMOS differential input pair.
XNM5 NET29 VINP NET21 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1+DESVAR_M2}
XNM6 NET22 VINN NET21 VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W3} L={DESVAR_L3} m={DESVAR_M1+DESVAR_M2}

* First-stage PMOS current-mirror load.
XPM9  NET22 NET22 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}
XPM10 NET29 NET22 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W4} L={DESVAR_L4} m={DESVAR_M1}

* Additional matched PMOS branch-current sources.
* Their W5/L5 remain independently adjustable.
XPM4 NET22 IB1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}
XPM5 NET29 IB1 VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W5} L={DESVAR_L5} m={DESVAR_M2}

* Second stage: NMOS common-source device and PMOS current source.
XNM11 VOUT NET29 VSS VSS sky130_fd_pr__nfet_01v8_lvt W={DESVAR_W6} L={DESVAR_L6} m={2*(DESVAR_M1+DESVAR_M2)*DESVAR_M3}
XPM3  VOUT IB1   VDD VDD sky130_fd_pr__pfet_01v8_lvt W={DESVAR_W1} L={DESVAR_L1} m={2*(DESVAR_M1+DESVAR_M2)*DESVAR_M3}

* Miller compensation with a series resistor.
RR0 NET29 NET1 {RNULL_OHM}
CC0 NET1 VOUT {CCOMP_F}

.ends DUT