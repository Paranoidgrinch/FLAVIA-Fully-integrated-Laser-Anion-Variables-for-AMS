# backend/config.py
from dataclasses import dataclass
from typing import Optional, Dict, List
from opcua.ua import VariantType

MQTT_DEFAULT_HOST = "192.168.0.20"
MQTT_DEFAULT_PORT = 1883
MQTT_DEFAULT_KEEPALIVE = 30

OPC_DEFAULT_URL = "opc.tcp://DESKTOP-UH9J072:4980/Softing_dataFEED_OPC_Suite_Configuration2"


@dataclass
class ChannelConfig:
    """Konfiguration eines logischen Kanals (OPC, MQTT, etc.)."""
    name: str
    unit: str = ""
    decimals: int = 1
    kind: str = "analog"   # 'analog', 'digital', 'mqtt', 'status', 'derived'
    opc_node_id: Optional[str] = None
    opc_variant_type: Optional[VariantType] = None
    opc_read: bool = False
    opc_write: bool = False
    mqtt_topic: Optional[str] = None
    mqtt_is_setpoint: bool = False


# Alle Kanäle des Systems zentral definiert
CHANNELS: Dict[str, ChannelConfig] = {
    # ----------------------- Digitale Ausgänge ----------------------------
    "do_attenuator": ChannelConfig(
        name="do_attenuator",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Attenuator",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),
    "do_cup1": ChannelConfig(
        name="do_cup1",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup1",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),
    "do_cup2": ChannelConfig(
        name="do_cup2",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup2",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),
    "do_cup3": ChannelConfig(
        name="do_cup3",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup3",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),
    "do_cup4": ChannelConfig(
        name="do_cup4",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup4",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),
    "do_cup5": ChannelConfig(
        name="do_cup5",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Cup5",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),
    "do_quick_cool": ChannelConfig(
        name="do_quick_cool",
        kind="digital",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Digital_Out/Quick-Cool",
        opc_variant_type=VariantType.Boolean,
        opc_read=True,
        opc_write=True,
    ),

    # ---------------------- Ofen / Temperatur ----------------------------
    "oven_current_set": ChannelConfig(
        name="oven_current_set",
        unit="A",
        decimals=2,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_HV/Analog_Out/Out_Cal_Ofen",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "oven_temp_meas": ChannelConfig(
        name="oven_temp_meas",
        unit="°C",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Ofen_Temp",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    # ---------------------- Ion Source (Sputter, Extraction) -------------
    "sputter_voltage_set": ChannelConfig(
        name="sputter_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_HV/Analog_Out/Out_Cal_Sputter_U",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "sputter_voltage_meas": ChannelConfig(
        name="sputter_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Sputter_U",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),
    "sputter_current_meas": ChannelConfig(
        name="sputter_current_meas",
        unit="mA",
        decimals=3,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Sputter_I",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),
    "ionizer_current_meas": ChannelConfig(
        name="ionizer_current_meas",
        unit="A",
        decimals=3,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_HV/Analog_In/In_Cal_Ionisierer",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "extraction_voltage_set": ChannelConfig(
        name="extraction_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Extraktion",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "extraction_voltage_meas": ChannelConfig(
        name="extraction_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Extraktion",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "einzellinse_voltage_set": ChannelConfig(
        name="einzellinse_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Einzellinse",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "einzellinse_voltage_meas": ChannelConfig(
        name="einzellinse_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Einzellinse",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    # Delta-Spannung (nur logischer Kanal)
    "delta_voltage": ChannelConfig(
        name="delta_voltage",
        unit="V",
        decimals=1,
        kind="derived",
    ),

    # ---------------------- Ion Optics -----------------------------------
    "lens2_voltage_set": ChannelConfig(
        name="lens2_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Linse2",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "lens2_voltage_meas": ChannelConfig(
        name="lens2_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Linse2",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "ion_cooler_voltage_set": ChannelConfig(
        name="ion_cooler_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Ionenkuehler",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "ion_cooler_voltage_meas": ChannelConfig(
        name="ion_cooler_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Ionenkuehler",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "quad1_voltage_set": ChannelConfig(
        name="quad1_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Quad1",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "quad1_voltage_meas": ChannelConfig(
        name="quad1_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Quad1",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),
    "quad2_voltage_set": ChannelConfig(
        name="quad2_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Quad2",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "quad2_voltage_meas": ChannelConfig(
        name="quad2_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Quad2",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),
    "quad3_voltage_set": ChannelConfig(
        name="quad3_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Quad3",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "quad3_voltage_meas": ChannelConfig(
        name="quad3_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Quad3",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "esa_voltage_set": ChannelConfig(
        name="esa_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_ESA",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "esa_voltage_meas": ChannelConfig(
        name="esa_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_ESA",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "esa_correction_set": ChannelConfig(
        name="esa_correction_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_ESA_Z",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "esa_correction_meas": ChannelConfig(
        name="esa_correction_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_ESA_Z",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    "lens4_voltage_set": ChannelConfig(
        name="lens4_voltage_set",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_Out/Out_Cal_Linse4",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=True,
    ),
    "lens4_voltage_meas": ChannelConfig(
        name="lens4_voltage_meas",
        unit="V",
        decimals=1,
        kind="analog",
        opc_node_id="ns=3;s=OPC_1.PLC_GND1/Analog_In/In_Cal_Linse4",
        opc_variant_type=VariantType.Float,
        opc_read=True,
        opc_write=False,
    ),

    # ---------------------- MQTT Kanäle (PSU/HV) ------------------------
    "gf1_set": ChannelConfig(
        name="gf1_set",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="psu/1/cmd/set_v",
        mqtt_is_setpoint=True,
    ),
    "gf1_meas_v": ChannelConfig(
        name="gf1_meas_v",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="psu/1/meas_v",
        mqtt_is_setpoint=False,
    ),

    "gf2_set": ChannelConfig(
        name="gf2_set",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="psu/2/cmd/set_v",
        mqtt_is_setpoint=True,
    ),
    "gf2_meas_v": ChannelConfig(
        name="gf2_meas_v",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="psu/2/meas_v",
        mqtt_is_setpoint=False,
    ),

    "hv1_set": ChannelConfig(
        name="hv1_set",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="hv/1/cmd/set_v",
        mqtt_is_setpoint=True,
    ),
    "hv1_meas_v": ChannelConfig(
        name="hv1_meas_v",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="hv/1/meas_v",
        mqtt_is_setpoint=False,
    ),
    "hv1_meas_i": ChannelConfig(
        name="hv1_meas_i",
        unit="mA",
        decimals=1,
        kind="mqtt",
        mqtt_topic="hv/1/meas_i_mA",
        mqtt_is_setpoint=False,
    ),

    "hv4_set": ChannelConfig(
        name="hv4_set",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="hv/4/cmd/set_v",
        mqtt_is_setpoint=True,
    ),
    "hv4_meas_v": ChannelConfig(
        name="hv4_meas_v",
        unit="V",
        decimals=1,
        kind="mqtt",
        mqtt_topic="hv/4/meas_v",
        mqtt_is_setpoint=False,
    ),
    "hv4_meas_i": ChannelConfig(
        name="hv4_meas_i",
        unit="mA",
        decimals=1,
        kind="mqtt",
        mqtt_topic="hv/4/meas_i_mA",
        mqtt_is_setpoint=False,
    ),


    # ---------------------- Magnet / Gaussmeter ------------------------
    "magnet_current_set": ChannelConfig(
        name="magnet_current_set",
        unit="A",
        decimals=3,
        kind="analog",
    ),
    "magnet_current_meas": ChannelConfig(
        name="magnet_current_meas",
        unit="A",
        decimals=4,
        kind="analog",
    ),
    "magnet_voltage_meas": ChannelConfig(
        name="magnet_voltage_meas",
        unit="V",
        decimals=3,
        kind="analog",
    ),
    "magnet_field_meas": ChannelConfig(
        name="magnet_field_meas",
        unit="kG",
        decimals=3,
        kind="analog",
    ),

    "magnet_connected": ChannelConfig(
        name="magnet_connected",
        kind="status",
    ),
    "gaussmeter_connected": ChannelConfig(
        name="gaussmeter_connected",
        kind="status",
    ),


    # ---------------------- Keithley picoammeter ----------------------
    "keithley_current_nA": ChannelConfig(
        name="keithley_current_nA",
        unit="nA",
        decimals=2,
        kind="analog",
    ),
    "keithley_current_nA_avg_1s": ChannelConfig(
        name="keithley_current_nA_avg_1s",
        unit="nA",
        decimals=2,
        kind="analog",
    ),
    "keithley_current_nA_sigma_1s": ChannelConfig(
        name="keithley_current_nA_sigma_1s",
        unit="nA",
        decimals=2,
        kind="analog",
    ),

    # ---------------------- Status-Kanäle --------------------------------
    "opc_connected": ChannelConfig(
        name="opc_connected",
        kind="status",
    ),
    "mqtt_connected": ChannelConfig(
        name="mqtt_connected",
        kind="status",
    ),
    "keithley_connected": ChannelConfig(
        name="keithley_connected",
        kind="status",
    ),
}


# Logging-Kanäle in der gewünschten Reihenfolge
BACKEND_LOG_CHANNELS: List[str] = [
    # Digital
    "do_attenuator", "do_cup1", "do_cup2", "do_cup3", "do_cup4", "do_cup5", "do_quick_cool",
    # Analoge OPC-Messwerte
    "oven_temp_meas", "sputter_voltage_meas", "sputter_current_meas",
    "ionizer_current_meas", "extraction_voltage_meas", "einzellinse_voltage_meas",
    "lens2_voltage_meas", "ion_cooler_voltage_meas", "quad1_voltage_meas",
    "quad2_voltage_meas", "quad3_voltage_meas", "esa_voltage_meas",
    "esa_correction_meas", "lens4_voltage_meas",
    # MQTT
    "gf1_set", "gf1_meas_v",
    "gf2_set", "gf2_meas_v",
    "hv1_set", "hv1_meas_v", "hv1_meas_i",
    "hv4_set", "hv4_meas_v", "hv4_meas_i",
    #Magnet
    "magnet_current_meas",
    "magnet_voltage_meas",
    "magnet_field_meas",
    "keithley_current_nA_avg_1s",

]
