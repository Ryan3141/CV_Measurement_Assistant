if __name__ == "__main__": # This allows running this module by running this script
	import pathlib
	import sys
	this_files_directory = pathlib.Path(__file__).parent.resolve()
	sys.path.insert(0, str(this_files_directory.parent.resolve()) ) # Add parent directory to access other modules

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QFileDialog
try:
	from PyQt5 import uic
except ImportError:
	import sip
import sys

import numpy as np
import time
from threading import Event

from MPL_Shared.Temperature_Controller import Temperature_Controller
from MPL_Shared.Temperature_Controller_Settings import TemperatureControllerSettingsWindow
from MPL_Shared.SQL_Controller import Commit_XY_Data_To_SQL, Connect_To_SQL
from MPL_Shared.Async_Iterator import Async_Iterator, Run_Async
from MPL_Shared.Saveable_Session import Saveable_Session
from CV_Measurement_Assistant.CV_Box_Controller import CV_Controller
from CV_Measurement_Assistant.Measurement_Loop import Measurement_Loop

from MPL_Shared.Pad_Description_File import Get_Device_Description_File
from MPL_Shared.GUI_Tools import Popup_Error, Popup_Yes_Or_No, resource_path, Measurement_Sweep_Runner
from MPL_Shared.Threaded_Subsystems import Threaded_Subsystems

from rich import print

__version__ = '2.00'


Ui_MainWindow, QtBaseClass = uic.loadUiType( resource_path("CV_GUI.ui") ) # GUI layout file.


class CV_Measurement_Assistant_App( QtWidgets.QWidget, Ui_MainWindow, Saveable_Session, Threaded_Subsystems ):

	measurementRequested_signal = QtCore.pyqtSignal(float, float, float, float, float, float)

	def __init__(self, parent=None, root_window=None):
		QtWidgets.QWidget.__init__(self, parent)
		Ui_MainWindow.__init__(self)
		self.setupUi(self)

		Saveable_Session.__init__( self, text_boxes = [(self.user_lineEdit, "user"),(self.descriptionFilePath_lineEdit, "pad_description_path"),(self.sampleName_lineEdit, "sample_name"),
					   (self.startVoltage_lineEdit, "start_v"),(self.endVoltage_lineEdit, "end_v"), (self.stepVoltage_lineEdit, "step_v"),
					   (self.startTemp_lineEdit, "start_T"),(self.endTemp_lineEdit, "end_T"), (self.stepTemp_lineEdit, "step_T")] )

		self.Init_Subsystems()
		self.Connect_Control_Logic()
		self.Start_Subsystems()

		self.Restore_Session( resource_path( "session.ini" ) )

		self.current_data = None
		self.measurement = None

	def closeEvent( self, event ):
		if self.measurement:
			self.quit_early.set()
			self.measurement.wait()
		self.graph.close()
		Threaded_Subsystems.closeEvent(self, event)
		QtWidgets.QWidget.closeEvent(self, event)

	def Init_Subsystems( self ):
		self.sql_type, self.sql_conn = Connect_To_SQL( resource_path( "configuration.ini" ), config_error_popup=Popup_Yes_Or_No )
		self.config_window = TemperatureControllerSettingsWindow()
		self.measurement = None

		self.quit_early = Event()
		status_layout = self.connectionsStatusDisplay_widget.layout()
		subsystems = self.Make_Subsystems( self, status_layout,
		                                   CV_Controller(),
		                                   Temperature_Controller( resource_path( "configuration.ini" ) ) )
		self.cv_controller, self.temp_controller = subsystems


		self.graph.set_labels( title="C-V", x_label="Voltage (V)", y_label="Capacitance (C)" )

	def Open_Config_Window( self ):
		self.config_window.show()
		getattr(self.config_window, "raise")()
		self.config_window.activateWindow()

	def Connect_Control_Logic( self ):
		self.Stop_Measurement() # Initializes Measurement Sweep Button

		#self.establishComms_pushButton.clicked.connect( self.Establish_Comms )
		self.takeMeasurement_pushButton.clicked.connect( self.Take_Single_Measurement )
		self.outputToFile_pushButton.clicked.connect( self.Save_Data_To_File )
		self.saveToDatabase_pushButton.clicked.connect( self.Save_Data_To_Database )
		self.clearGraph_pushButton.clicked.connect( self.graph.clear_all_plots )

		self.measurementRequested_signal.connect( self.cv_controller.Voltage_Sweep )
		self.cv_controller.newSweepStarted_signal.connect( self.graph.new_plot )
		self.cv_controller.dataPointGotten_signal.connect( self.graph.add_new_data_point )
		self.cv_controller.sweepFinished_signal.connect( self.graph.plot_finished )
		self.cv_controller.Error_signal.connect( self.Error_During_Measurement )

		# Temperature controller stuff
		self.config_window.Connect_Functions( self.temp_controller )
		self.settings_pushButton.clicked.connect( self.Open_Config_Window )
		self.loadDevicesFile_pushButton.clicked.connect( self.Select_Device_File )

		# Update labels on connection and disconnection to wifi devices
		self.temp_controller.Temperature_Changed.connect( lambda temperature : self.currentTemp_lineEdit.setText( '{:.2f}'.format( temperature ) ) )
		self.temp_controller.PID_Output_Changed.connect( lambda pid_output : self.outputPower_lineEdit.setText( '{:.2f} %'.format( pid_output ) ) )



	def Select_Device_File( self ):
		fileName, _ = QFileDialog.getOpenFileName( self, "QFileDialog.getSaveFileName()", "", "CSV Files (*.csv);;All Files (*)" )
		if fileName == "": # User cancelled
			return
		try:
			config_info = Get_Device_Description_File( fileName )
		except Exception as e:
			Popup_Error( "Error", str(e) )
			return

		self.descriptionFilePath_lineEdit.setText( fileName )

	def Get_Measurement_Sweep_User_Input( self ):
		sample_name = self.sampleName_lineEdit.text()
		user = str( self.user_lineEdit.text() )
		if( sample_name == "" or user == "" ):
			raise ValueError( "Must enter a sample name and user" )

		try:
			temp_start, temp_end, temp_step = float(self.startTemp_lineEdit.text()), float(self.endTemp_lineEdit.text()), float(self.stepTemp_lineEdit.text())
			v_start, v_end, v_step = float(self.startVoltage_lineEdit.text()), float(self.endVoltage_lineEdit.text()), float(self.stepVoltage_lineEdit.text())
			ac_voltage = float( self.acVoltage_lineEdit.text() )
			ac_frequency = float( self.acFrequency_lineEdit.text() )
			step_delay = float( self.stepDelay_lineEdit.text() )
		except ValueError:
			raise ValueError( "Invalid arguement for temperature, timing, or voltage range" )

		device_config_data = Get_Device_Description_File( self.descriptionFilePath_lineEdit.text() )

		self.sql_type, self.sql_conn = Connect_To_SQL( resource_path( "configuration.ini" ) )
		meta_data = dict( sample_name=sample_name, user=user, measurement_setup="LN2 Dewar" )

		return meta_data, (temp_start, temp_end, temp_step), (v_start, v_end, v_step, step_delay), (ac_voltage, ac_frequency), device_config_data

	def Error_During_Measurement( self, error ):
		self.quit_early.set()
		self.Make_Safe()
		Popup_Error( "Error During Measurement:", error )

	def Start_Measurement( self ):
		# Update button to reuse it for stopping measurement
		try:
			self.Save_Session( resource_path( "session.ini" ) )
			self.quit_early.clear()
			self.measurement = Measurement_Sweep_Runner( self, self.Stop_Measurement, self.quit_early, Measurement_Sweep,
			                                             self.temp_controller, self.cv_controller,
							                             *self.Get_Measurement_Sweep_User_Input() )
		except Exception as e:
			Popup_Error( "Error Starting Measurement", str(e) )
			return

		# Update button to reuse it for stopping measurement
		try: self.takeMeasurementSweep_pushButton.clicked.disconnect()
		except Exception: pass
		self.takeMeasurementSweep_pushButton.setText( "Stop Measurement" )
		self.takeMeasurementSweep_pushButton.setStyleSheet("QPushButton { background-color: rgba(255,0,0,255); color: rgba(0, 0, 0,255); }")
		self.takeMeasurementSweep_pushButton.clicked.connect( self.Stop_Measurement )


	def Stop_Measurement( self ):
		self.quit_early.set()

		try: self.takeMeasurementSweep_pushButton.clicked.disconnect()
		except Exception: pass
		self.takeMeasurementSweep_pushButton.setText( "Measurement Sweep" )
		self.takeMeasurementSweep_pushButton.setStyleSheet("QPushButton { background-color: rgba(0,255,0,255); color: rgba(0, 0, 0,255); }")
		self.takeMeasurementSweep_pushButton.clicked.connect( self.Start_Measurement )

	def Set_Current_Data( self, x_data, y_data ):
		self.current_data = ( x_data, y_data )
		self.cv_controller.sweepFinished_signal.disconnect( self.Set_Current_Data )

	def Take_Single_Measurement( self ):
		input_start = float( self.startVoltage_lineEdit.text() )
		input_end = float( self.endVoltage_lineEdit.text() )
		input_step = float( self.stepVoltage_lineEdit.text() )
		ac_voltage = float( self.acVoltage_lineEdit.text() )
		ac_frequency = float( self.acFrequency_lineEdit.text() )
		step_delay = float( self.stepDelay_lineEdit.text() )

		self.cv_controller.sweepFinished_signal.connect( self.Set_Current_Data )
		self.measurementRequested_signal.emit( input_start, input_end, input_step, ac_voltage, ac_frequency, step_delay )

	def Save_Data_To_File( self ):
		if self.sampleName_lineEdit.text() == '':
			Popup_Error( "Error", "Must enter sample name" )
			return

		timestr = time.strftime("%Y%m%d-%H%M%S")
		sample_name = str( self.sampleName_lineEdit.text() )

		file_name = "CV Data_" + sample_name + "_" + timestr + ".csv"
		print( "Saving File: " + file_name )
		with open( file_name, 'w' ) as outfile:
			for x,y in zip( self.current_data[0], self.current_data[1] ):
				outfile.write( f'{x},{y}\n' )

	def Save_Data_To_Database( self ):
		if self.current_data == None:
			return

		sample_name = str( self.sampleName_lineEdit.text() )
		user = str( self.user_lineEdit.text() )
		if sample_name == ''  or user == '':
			Popup_Error( "Error", "Must enter sample name and user" )
			return

		meta_data_sql_entries = dict( sample_name=sample_name, user=user, temperature_in_k=None, measurement_setup="Microprobe",
					device_location=None, device_side_length_in_um=None, blackbody_temperature_in_c=None,
					bandpass_filter=None, aperture_radius_in_m=None )

		Commit_XY_Data_To_SQL( self.sql_type, self.sql_conn, xy_data_sql_table="cv_raw_data", xy_sql_labels=("voltage_v","capacitance_f"),
						   x_data=self.current_data[0], y_data=self.current_data[1], metadata_sql_table="cv_measurements", **meta_data_sql_entries )

		print( "Data committed to database: " + sample_name  )


def Measurement_Sweep( quit_early,
                       temp_controller, cv_controller,
                       meta_data, temperature_info, voltage_sweep_info, ac_voltage_info, device_config_data ):
	sql_type, sql_conn = Connect_To_SQL( resource_path( "configuration.ini" ) )

	run_devices  = Async_Iterator( device_config_data,
	                               temp_controller, lambda current_device, temp_controller=temp_controller : temp_controller.Set_Active_Pads( current_device.neg_pad, current_device.pos_pad ),
	                               temp_controller.Pads_Selected_Changed,
	                               quit_early )

	if temperature_info is None:
		turn_off_heater = [None]
		turn_heater_back_on = [None]
		run_temperatures = [None]
	else:
		turn_off_heater = Async_Iterator( [None],
		                                  temp_controller, lambda _ : temp_controller.Turn_Off(),
		                                  temp_controller.Heater_Output_Off,
		                                  quit_early )
		turn_heater_back_on = Async_Iterator( [None],
		                                      temp_controller, lambda _ : temp_controller.Turn_On(),
		                                      temp_controller.Temperature_Stable,
		                                      quit_early )
		temp_start, temp_end, temp_step = temperature_info
		run_temperatures = Async_Iterator( np.arange( temp_start, temp_end + temp_step / 2, temp_step ),
		                                   temp_controller, temp_controller.Set_Temp_And_Turn_On,
		                                   temp_controller.Temperature_Stable,
		                                   quit_early )

	v_start, v_end, v_step, step_delay = voltage_sweep_info
	ac_voltage, ac_frequency = ac_voltage_info
	meta_data.update( { "ac_amplitude_v":ac_voltage, "ac_frequency_hz":ac_frequency } )
	get_results = Async_Iterator( [None],
	                              cv_controller, lambda *args, v_start=v_start, v_end=v_end, v_step=v_step, ac_voltage=ac_voltage, ac_frequency=ac_frequency, step_delay=step_delay :
	                                                    cv_controller.Voltage_Sweep( v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay ),
	                              cv_controller.sweepFinished_signal,
	                              quit_early )

	# for temperature in run_temperatures:
	# 	for device, pads_info in run_devices:
	# 		for _ in turn_heater_back_on:
	for temperature, (device, pads_info), _ in ((x,y,z) for x in run_temperatures for y in run_devices for z in turn_heater_back_on ):
		meta_data.update( dict( temperature_in_k=temperature, device_location=device.location, device_side_length_in_um=device.side ) )
		(neg_pad, pos_pad), pads_are_reversed = pads_info
		print( f"Starting Measurement for {device.location} side length {device.side} at {temperature} K on pads {neg_pad} and {pos_pad}" )

		for _, xy_data in ((x,y) for x in turn_off_heater for y in get_results ):
			x_data, y_data, q_data = xy_data
			if pads_are_reversed:
				x_data = x_data[::-1]
				y_data = y_data[::-1]
				q_data = q_data[::-1]
			Commit_XY_Data_To_SQL( sql_type, sql_conn, xy_data_sql_table="cv_raw_data", xy_sql_labels=("voltage_v","capacitance_f"),
								x_data=x_data, y_data=y_data, metadata_sql_table="cv_measurements", **meta_data )

	test1 = Run_Async( temp_controller, lambda : temp_controller.Make_Safe() ); test1.Run()

	print( "Finished Measurment" )


if __name__ == "__main__":
	app = QtWidgets.QApplication( sys.argv )
	window = CV_Measurement_Assistant_App()
	window.show()
	sys.exit( app.exec_() )
