# Interface for Keysight E4980 outlined in this document: https://literature.cdn.keysight.com/litweb/pdf/E4980-90210.pdf

try:
	import visa
except:
	from MPL_Shared.Install_If_Necessary import Ask_For_Install
	Ask_For_Install( "PyVisa" )
	import visa
import numpy as np
import time

from PyQt5 import QtCore


class CV_Controller( QtCore.QObject ):
	newSweepStarted_signal = QtCore.pyqtSignal()
	dataPointGotten_signal = QtCore.pyqtSignal(float, float)
	sweepFinished_signal = QtCore.pyqtSignal(np.ndarray, np.ndarray)

	controllerConnected_signal = QtCore.pyqtSignal()
	controllerDisconnected_signal = QtCore.pyqtSignal()

	def __init__( self, parent=None ):
		super(CV_Controller, self).__init__(parent)
		self.Measurement_Box = None
		self.debug = 1
		self.stop_measurement_early = False

	def Run( self ):
		self.resource_manager = visa.ResourceManager()
		self.Initialize_Connection()

	def Close_Connection():
		self.Measurement_Box.close()
		self.Measurement_Box = None
		self.controllerDisconnected_signal.emit()


	def Initialize_Connection( self ):
		if self.Measurement_Box != None:
			return
		#print( self.resource_manager.list_resources() ) # List available machines to connect to

		try: # For usb connection use "USB0::2391::2313::MY12345678::0::INSTR"
			self.Measurement_Box = self.resource_manager.open_resource('GPIB0::17::INSTR') # Keysight E4980's address on GPIB connection with IEEE-446 protocol
			self.controllerConnected_signal.emit()
			return self.Measurement_Box
		except:
			return None

	def Close_Connection( self ):
		if self.Measurement_Box == None:
			return

		self.Measurement_Box.close()
		self.Measurement_Box = None


	def Voltage_Sweep( self, v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay=0.5 ):
		Measurement_Box = self.Measurement_Box

		# Pretend data to test graphing
		if Measurement_Box == None:
			x_values = np.arange( v_start, v_end + v_step, v_step )
			self.newSweepStarted_signal.emit()
			time.sleep( 0.1 )

			for index, x in enumerate(x_values):
				self.dataPointGotten_signal.emit( x, x * 100E-3 * self.debug )
				time.sleep( 0.01 )
			self.sweepFinished_signal.emit( x_values, x_values )
			self.debug += 1
			return

		x_values = np.arange( v_start, v_end + v_step, v_step )
		bias_list = ','.join([ f'{x:E}' for x in x_values ])
		assert len(x_values) <= 201, "Number of voltage points to sweep must be no more than 201"
		assert ac_voltage <= 20 and ac_voltage >= 0, "ac_voltage must be between 0 and 20 Volts"
		assert ac_frequency <= 2E6 and ac_frequency >= 20, "ac_voltage must be between 20Hz and 2MHz"
		assert step_delay <= 999 and step_delay >= 0, "step_delay must be between 0 and 999 seconds"

		
		empty_data_point = "9.9E37" # np.nan
		Measurement_Box = self.Measurement_Box
		self.newSweepStarted_signal.emit()
		Measurement_Box.write( "*RST;*CLS" ) # Reset everything to known good state (factory defaults)
		Measurement_Box.write( ":DISPLAY:CCLEAR" ) # Clears any lingering error messages
		Measurement_Box.write( ":TRIGGER:SOURCE BUS" ) # Sets trigger source to "GPIB/LAN/USB"
		Measurement_Box.write( ":FORMAT ASCII" ) # Sets the transfer mode to ASCII
		Measurement_Box.write( f":FREQUENCY {ac_frequency:e}" ) # Sets ac voltage frequency (in Hz) to use during the measurements
		Measurement_Box.write( f":TRIGGER:DELAY {step_delay:e}" ) # Sets delay (in seconds) between successive measurements (not including settling delay)

		#Measurement_Box.write( ":APERTURE LONG,5" ) # Sets the time window to capture a measurement
		#Measurement_Box.write( ":OUTPUT:DC:ISOLATION ON" ) # Enables DC Isolation
		#Measurement_Box.write( ":AMPLITUDE:ALC ON" ) # Turns on automatic leveling control for holding the requested voltage
		#Measurement_Box.write( f':DISPLAY:LINE "{message}"' ) # Displays message on the LCD screen, can be no longer than 30 characters

		#timestr = time.strftime("%Y%m%d-%H%M%S")
		Measurement_Box.write( ":LIST:MODE SEQUENCE" ) # Sets the list sweep mode to sequence mode, when triggered once, the device is measured at all sweep points.
		#bias_list = ','.join([ f'{float(x):E}' for x in np.linspace( 1E-3, 10E-3, 10 )])
		Measurement_Box.write( ":LIST:BIAS:VOLTAGE " + bias_list ) # Sets voltages (in Volts) to sweep through
		#frequency_list = ','.join([ f'{float(x):E}' for x in range(1000, 10000+1, 1000) ])
		#Measurement_Box.write( ":LIST:FREQUENCY " + frequency_list ) # Sets voltages (in Volts) to sweep through
		Measurement_Box.write( ":DISPLAY:PAGE LIST" ) # Sets displayed page to <LIST SWEEP DISPLAY>

		#for i in range( 1, len(bias_list) + 2 ):
		#	Measurement_Box.write( f"LIST:BAND{i} A,1E-4,2E-4" ) # Begins the measurement sweep

		#Measurement_Box.write( f":MEMORY:DIM DBUF, {1}" ) # Clears data buffer memory and sets the data buffer memory's size
		#Measurement_Box.write( f":MEMORY:DIM DBUF, {len(x_values)}" ) # Clears data buffer memory and sets the data buffer memory's size
		#Measurement_Box.write( ":MEMORY:CLEAR DBUF" ) # Clears the data buffer memory and disables it from storing measurement data
		#Measurement_Box.write( ":MEMORY:FILL DBUF" ) # Enables the data buffer memory to store measurement data
		#Measurement_Box.write( ":APERTURE LONG,5" ) # Sets the measurement time mode and the averaging rate
		Measurement_Box.write( ":BIAS:STATE ON" )
		Measurement_Box.write( ":INITIATE:CONTINUOUS ON" ) # Prepares instrument for the measurement sweep
		#Measurement_Box.write( ":INITIATE:IMMEDIATE" ) # Prepares instrument for the measurement sweep
		Measurement_Box.write( ":TRIGGER:IMMEDIATE" ) # Begins the measurement sweep

		#Measurement_Box.write( ":MEMORY:READ? DBUF" ) # Begin reading the data
		#results = []
		#for index, x in enumerate(x_values):
		#	data = Measurement_Box.read()
		#	#print( data )
		#	results.append( float(data) )
		#	self.dataPointGotten_signal.emit( x, float(data) )
		#	if index % 10 == 0:
		#		QtCore.QCoreApplication.processEvents()
		#		if self.stop_measurement_early == True:
		#			self.stop_measurement_early = False
		#			break


		Measurement_Box.write( ":SYSTEM:BEEPER:TONE 1" ) # Makes a beep (1 - 5)
		Measurement_Box.write( ":SYSTEM:BEEPER:IMMEDIATE" ) # Makes a beep (1 - 5)
		Measurement_Box.timeout = 120000 # The measurement may take up to 120 seconds
		results = Measurement_Box.query_ascii_values(":FETCH:IMPEDANCE?", container=np.array)
		Measurement_Box.write( ":BIAS:STATE OFF" )
		#results = Measurement_Box.query_ascii_values(":MEMORY:READ? DBUF", container=np.array)
		by_measurement = np.reshape( results, (len(results)//4,4) )
		test = [x[0] for x in by_measurement]
		Measurement_Box.write( ":MEMORY:CLEAR DBUF" ) # Clears the data buffer memory and disables it from storing measurement data
		#results = Measurement_Box.read()
		self.sweepFinished_signal.emit( x_values, np.array(test) )



if __name__ == "__main__":
	test = CV_Controller()
	test.Run()

	v_start = -1.0
	v_end = 1.0
	v_step = 0.1
	ac_voltage = 1E-6
	ac_frequency = 1E4
	step_delay = 0.5
	test.Voltage_Sweep(v_start, v_end, v_step, ac_voltage, ac_frequency, step_delay)
	#QMetaObject.invokeMethod( test, 'Voltage_Sweep', Qt.AutoConnection,
	#				  Q_RETURN_ARG('int'), Q_ARG(float, v_start), Q_ARG(float, v_end), Q_ARG(float, v_step), Q_ARG(float, ac_voltage), Q_ARG(float, ac_frequency), Q_ARG(float, step_delay) )
