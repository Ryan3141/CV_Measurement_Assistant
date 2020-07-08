if __name__ == "__main__": # This allows running this module by running this script
	import sys
	sys.path.insert(0, "..")

import sys
from PyQt5 import uic, QtWidgets
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QFileDialog
from PyQt5.QtCore import QMetaObject, Q_RETURN_ARG, Q_ARG
from PyQt5 import QtCore

import numpy as np
import configparser
import time
import os

from MPL_Shared.Temperature_Controller import Temperature_Controller
from MPL_Shared.Temperature_Controller_Settings import TemperatureControllerSettingsWindow
from MPL_Shared.SQL_Controller import Commit_XY_Data_To_SQL, Connect_To_SQL
from CV_Measurement_Assistant.CV_Box_Controller import CV_Controller
from CV_Measurement_Assistant.Measurement_Loop import Measurement_Loop

from MPL_Shared.Pad_Description_File import Get_Device_Description_File

base_path = os.path.dirname( os.path.realpath(__file__) )

def resource_path(relative_path = ""):  # Define function to import external files when using PyInstaller.
    """ Get absolute path to resource, works for dev and for PyInstaller """
    return os.path.join(base_path, relative_path)

Ui_MainWindow, QtBaseClass = uic.loadUiType( resource_path("CV_GUI.ui") )

def Popup_Error( title, message ):
	error = QtWidgets.QMessageBox()
	error.setIcon( QtWidgets.QMessageBox.Critical )
	error.setText( message )
	error.setWindowTitle( title )
	error.setStandardButtons( QtWidgets.QMessageBox.Ok )
	return_value = error.exec_()
	return

def Popup_Yes_Or_No( title, message ):
	error = QtWidgets.QMessageBox()
	error.setIcon( QtWidgets.QMessageBox.Critical )
	error.setText( message )
	error.setWindowTitle( title )
	error.setStandardButtons( QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No )
	return_value = error.exec_()
	return return_value == QtWidgets.QMessageBox.Yes


def Controller_Connection_Changed( label, identifier, is_connected ):
	if is_connected:
		label.setText( str(identifier) + " Connected" )
		label.setStyleSheet("QLabel { background-color: rgba(0,255,0,255); color: rgba(0, 0, 0,255) }")
	else:
		label.setText( str(identifier) + " Not Connected" )
		label.setStyleSheet("QLabel { background-color: rgba(255,0,0,255); color: rgba(0, 0, 0,255) }")


class CV_Measurement_Assistant_App(QWidget, Ui_MainWindow):
	measurementRequested_signal = QtCore.pyqtSignal(float, float, float, float, float, float)

	def __init__(self, parent=None, root_window=None):
		QWidget.__init__(self, parent)
		Ui_MainWindow.__init__(self)
		self.setupUi(self)

		self.cv_Graph.set_labels( title="C-V", x_label="Voltage (V)", y_label="Capacitance (C)" )
		self.text_box_config = [(self.user_lineEdit, "user"),(self.descriptionFilePath_lineEdit, "pad_description_path"),(self.sampleName_lineEdit, "sample_name"),
					   (self.startVoltage_lineEdit, "start_v"),(self.endVoltage_lineEdit, "end_v"), (self.stepVoltage_lineEdit, "step_v"),
					   (self.startTemp_lineEdit, "start_T"),(self.endTemp_lineEdit, "end_T"), (self.stepTemp_lineEdit, "step_T")]
		self.current_data = None

		self.Init_Subsystems()
		self.Connect_Control_Logic()

		self.cv_controller_thread.start()
		self.temp_controller_thread.start()


	def Init_Subsystems(self):
		self.sql_type, self.sql_conn = Connect_To_SQL( resource_path( "configuration.ini" ), config_error_popup=Popup_Yes_Or_No )
		self.config_window = TemperatureControllerSettingsWindow()

		self.temp_controller = Temperature_Controller( resource_path( "configuration.ini" ) )
		self.temp_controller_thread = QtCore.QThread()
		self.temp_controller.moveToThread( self.temp_controller_thread )
		self.temp_controller_thread.started.connect( self.temp_controller.thread_start )

		self.cv_controller = CV_Controller()
		self.cv_controller_thread = QtCore.QThread()
		self.cv_controller.moveToThread( self.cv_controller_thread )
		self.cv_controller_thread.started.connect( self.cv_controller.Run )

		# Fill in user entry gui from config file entry
		configuration_file = configparser.ConfigParser()
		configuration_file.read( resource_path( "session.ini" ) )
		for box, name in self.text_box_config:
			try:
				text = configuration_file['TextBoxes'][name]
				if text:
					box.setText( text )
			except: pass


	def Open_Config_Window( self ):
		self.config_window.show()
		getattr(self.config_window, "raise")()
		self.config_window.activateWindow()

	def Connect_Control_Logic( self ):
		self.Stop_Measurment_Sweep() # Initializes Measurement Sweep Button

		#self.establishComms_pushButton.clicked.connect( self.Establish_Comms )
		self.takeMeasurement_pushButton.clicked.connect( self.Take_Single_Measurement )
		self.outputToFile_pushButton.clicked.connect( self.Save_Data_To_File )
		self.saveToDatabase_pushButton.clicked.connect( self.Save_Data_To_Database )
		self.clearGraph_pushButton.clicked.connect( self.cv_Graph.clear_all_plots )

		self.measurementRequested_signal.connect( self.cv_controller.Voltage_Sweep )
		self.cv_controller.newSweepStarted_signal.connect( self.cv_Graph.new_plot )
		self.cv_controller.dataPointGotten_signal.connect( self.cv_Graph.add_new_data_point )
		self.cv_controller.sweepFinished_signal.connect( self.cv_Graph.plot_finished )

		self.selectDescriptionFile_pushButton.clicked.connect( self.Select_Device_File )

		# Temperature controller stuff
		self.config_window.Connect_Functions( self.temp_controller )
		self.openConfigurationWindow_pushButton.clicked.connect( self.Open_Config_Window )

		# Update labels on connection and disconnection to wifi devices
		self.cv_controller.controllerConnected_signal   .connect( lambda : Controller_Connection_Changed( self.ivControllerConnected_label, "CV Controller", True ) )
		self.cv_controller.controllerDisconnected_signal.connect( lambda : Controller_Connection_Changed( self.ivControllerConnected_label, "CV Controller", False ) )
		self.temp_controller.Device_Connected.connect( lambda identifier, type_of_connection : Controller_Connection_Changed( self.tempControllerConnected_label, identifier, True ) )
		self.temp_controller.Device_Disconnected.connect( lambda : Controller_Connection_Changed( self.tempControllerConnected_label, "Temperature Controller", False ) )
		self.temp_controller.Temperature_Changed.connect( lambda temperature : self.currentTemp_lineEdit.setText( '{:.2f}'.format( temperature ) ) )
		self.temp_controller.PID_Output_Changed.connect( lambda pid_output : self.outputPower_lineEdit.setText( '{:.2f} %'.format( pid_output ) ) )



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


		#QMetaObject.invokeMethod( self.cv_controller, 'Voltage_Sweep', Qt.AutoConnection,
		#				  Q_RETURN_ARG('int'), Q_ARG(float, input_start), Q_ARG(float, input_end), Q_ARG(float, input_step) )
		#self.recent_results = (input_start = -1, input_end = 1, input_step = 0.01)

	def Save_Data_To_File( self ):
		if self.sampleName_lineEdit.text() == '':
			Popup_Error( "Error", "Must enter sample name" )
			return

		timestr = time.strftime("%Y%m%d-%H%M%S")
		sample_name = str( self.sampleName_lineEdit.text() )

		file_name = "CV Data_" + sample_name + "_" + timestr + ".csv"
		print( "Saving File: " + file_name )
		with open( file_name, 'w' ) as outfile:
			outfile.write( ','.join([str(x) for x in self.current_data[0]]) + '\n' )
			outfile.write( ','.join([str(x) for x in self.current_data[1]]) + '\n' )

	def Save_Data_To_Database( self ):
		if self.current_data == None:
			return

		sample_name = str( self.sampleName_lineEdit.text() )
		user = str( self.user_lineEdit.text() )
		if sample_name == ''  or user == '':
			Popup_Error( "Error", "Must enter sample name and user" )
			return

		meta_data_sql_entries = dict( sample_name=sample_name, user=user, temperature_in_k=None, measurement_setup="Microprobe",
					device_location=None, device_area_in_um2=None, device_perimeter_in_um=None, blackbody_temperature_in_c=None,
					bandpass_filter=None, aperture_radius_in_m=None )

		Commit_XY_Data_To_SQL( self.sql_type, self.sql_conn, xy_data_sql_table="cv_raw_data", xy_sql_labels=("voltage_v","capacitance_f"),
						   x_data=self.current_data[0], y_data=self.current_data[1], metadata_sql_table="cv_measurements", **meta_data_sql_entries )

		print( "Data committed to database: " + sample_name  )

	def Select_Device_File( self ):
		fileName, _ = QFileDialog.getOpenFileName( self, "QFileDialog.getSaveFileName()", "", "CSV Files (*.csv);;All Files (*)" )
		if fileName == "": # User cancelled
			return
		config_info = Get_Device_Description_File( fileName )
		if config_info is None:
			Popup_Error( "Error", "Invalid device file given" )
			return

		self.descriptionFilePath_lineEdit.setText( fileName )


	def Start_Measurement_Sweep( self ):
		try:
			temp_start, temp_end, temp_step = float(self.startTemp_lineEdit.text()), float(self.endTemp_lineEdit.text()), float(self.stepTemp_lineEdit.text())
			v_start, v_end, v_step = float(self.startVoltage_lineEdit.text()), float(self.endVoltage_lineEdit.text()), float(self.stepVoltage_lineEdit.text())
		except:
			Popup_Error( "Error", "Invalid arguement for temperature or voltage range" )
			return
		
		device_config_data = Get_Device_Description_File( self.descriptionFilePath_lineEdit.text() )
		if device_config_data is None:
			Popup_Error( "Error", "Invalid device file given" )
			return

		temperatures_to_measure = np.arange( temp_start, temp_end + temp_step, temp_step )
		sample_name = self.sampleName_lineEdit.text()
		user = str( self.user_lineEdit.text() )
		if( sample_name == "" or user == "" ):
			Popup_Error( "Error", "Must enter a sample name and user" )
			return

		# Save textbox contents from session
		configuration_file = configparser.ConfigParser()
		configuration_file.read( resource_path( "session.ini" ) )
		configuration_file['TextBoxes'] = {}
		for box, name in self.text_box_config:
			configuration_file['TextBoxes'][name] = box.text()
		with open(resource_path( "session.ini" ), 'w') as configfile:
			configuration_file.write( configfile )

		# Initialize Measurment Thread
		self.active_measurement = Measurement_Loop( sample_name, user, device_config_data, temperatures_to_measure, v_start, v_end + v_step, v_step )
		self.active_measurement_thread = QtCore.QThread()
		self.active_measurement.moveToThread( self.active_measurement_thread )
		self.active_measurement_thread.started.connect( self.active_measurement.Run )

		# Connect interactions with cv measurments and temperature control
		self.active_measurement.measurementRequested_signal.connect( self.cv_controller.Voltage_Sweep )
		self.active_measurement.Temperature_Change_Requested.connect( self.temp_controller.Set_Temp_And_Turn_On )
		self.temp_controller.Temperature_Stable.connect( self.cv_Graph.clear_all_plots )
		self.temp_controller.Temperature_Stable.connect( self.active_measurement.Temperature_Ready )
		self.temp_controller.Pads_Selected_Changed.connect( self.active_measurement.Pads_Ready )
		self.active_measurement.Pad_Change_Requested.connect( self.temp_controller.Set_Active_Pads )
		self.cv_controller.sweepFinished_signal.connect( self.active_measurement.Collect_Data )

		# Sweep thread finished
		self.active_measurement.Finished.connect( self.active_measurement_thread.quit )
		self.active_measurement_thread.finished.connect( self.active_measurement.deleteLater )
		self.active_measurement_thread.finished.connect( self.Stop_Measurment_Sweep )
		self.active_measurement_thread.finished.connect( self.temp_controller.Turn_Off )

		# Update button to reuse it for stopping measurement
		try: self.takeMeasurementSweep_pushButton.clicked.disconnect()
		except Exception: pass
		self.takeMeasurementSweep_pushButton.setText( "Stop Measurement" )
		self.takeMeasurementSweep_pushButton.setStyleSheet("QPushButton { background-color: rgba(255,0,0,255); color: rgba(0, 0, 0,255); }")
		self.takeMeasurementSweep_pushButton.clicked.connect( self.active_measurement.Quit_Early )

		self.active_measurement_thread.start()

	def Stop_Measurment_Sweep( self ):
		try: self.takeMeasurementSweep_pushButton.clicked.disconnect() 
		except Exception: pass	
		self.takeMeasurementSweep_pushButton.setText( "Measurement Sweep" )
		self.takeMeasurementSweep_pushButton.setStyleSheet("QPushButton { background-color: rgba(0,255,0,255); color: rgba(0, 0, 0,255); }")
		self.takeMeasurementSweep_pushButton.clicked.connect( self.Start_Measurement_Sweep )



if __name__ == '__main__':
	app = QApplication(sys.argv)
	ex = CV_Measurement_Assistant_App()
	ex.show()
	sys.exit(app.exec_())
