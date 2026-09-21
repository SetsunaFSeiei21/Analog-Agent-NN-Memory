* SKY130 OTA core with internally biased NMOS tail
* Standard testbench interface: VINP VINN VOUT VDD VSS

.include "five_t_ota_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Bias circuit: reference current and diode-connected NMOS are both inside DUT.
* IBIAS_A is a design parameter in amperes, not a testbench condition.
IBIAS_SRC VDD IBIAS DC {IBIAS_A}
XMBIAS IBIAS IBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS}

* NMOS differential pair
XMN1 N1 VINP NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN}
XMN2 VOUT VINN NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN}

* PMOS current-mirror load
XMP1 N1 N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD}
XMP2 VOUT N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD}

* NMOS tail current source
XMTAIL NTAIL IBIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LTAIL} W={WTAIL}

.ends DUT