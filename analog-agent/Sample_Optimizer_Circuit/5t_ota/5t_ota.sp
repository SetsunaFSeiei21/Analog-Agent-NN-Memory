* SKY130 five-transistor OTA converted from the Cadence topology.
* Standard testbench interface: VINP VINN VOUT VDD VSS.
* W/L use micrometers under the SKY130 PDK scale=1u option.
* M_FACTOR is shared by the input pair and PMOS load;
* the tail device uses twice this multiplicity.

.include "5t_ota_params.sp"

.subckt DUT VINP VINN VOUT VDD VSS

* Internal bias circuit corresponding to Cadence MNM3 and II0.
IBIAS_SRC VDD N_BIAS DC {IBIAS_A}
XMBIAS N_BIAS N_BIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m=1

* Tail current mirror corresponding to Cadence MNM2.
* It shares W/L with the diode-connected bias NMOS.
XMTAIL NTAIL N_BIAS VSS VSS sky130_fd_pr__nfet_01v8 L={LBIAS} W={WBIAS} m={2*M_FACTOR}

* NMOS differential pair corresponding to Cadence MNM0/MNM1.
XMN_INP N1 VINP NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN} m={M_FACTOR}
XMN_INN VOUT VINN NTAIL VSS sky130_fd_pr__nfet_01v8 L={LIN} W={WIN} m={M_FACTOR}

* PMOS current-mirror load corresponding to Cadence MPM0/MPM1.
XMP_DIODE N1 N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD} m={M_FACTOR}
XMP_OUT VOUT N1 VDD VDD sky130_fd_pr__pfet_01v8 L={LLOAD} W={WLOAD} m={M_FACTOR}

.ends DUT
