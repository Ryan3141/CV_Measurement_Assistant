from PyQt5 import QtCore


class Measurement_Loop( QtCore.QObject ):
	Finished = QtCore.pyqtSignal()
	Temperature_Change_Requested = QtCore.pyqtSignal( float )
	Pad_Change_Requested = QtCore.pyqtSignal( int, int )
	measurementRequested_signal = QtCore.pyqtSignal(float, float, float)
	Finished = QtCore.pyqtSignal()

	def __init__( self, sample_name, user, device_config_data, temperatures_to_measure, v_start, v_end, v_step, parent=None ):
		super().__init__( parent )
		self.sample_name = sample_name
		self.user = user
		self.temperatures_to_measure = temperatures_to_measure
		self.v_start = v_start
		self.v_end = v_end
		self.v_step = v_step
		self.sql_type, self.sql_conn = Connect_To_SQL( resource_path( "configuration.ini" ) )
		self.device_config_data = device_config_data

		self.pads_are_reversed = False
		self.temperature_ready = False
		self.pads_ready = False
		self.data_gathered = False
		self.quit_early = False
		self.data_collection_callback = lambda x_data, y_data : None

	def Wait_For_Temp_And_Pads( self ):
		while( not (self.temperature_ready and self.pads_ready) ):
			if self.quit_early:
				self.Finished.emit()
				return True
			time.sleep( 2 )
			QtCore.QCoreApplication.processEvents()
		self.temperature_ready = False
		self.pads_ready = False
		return False

	def Wait_For_Data( self ):
		while( not self.data_gathered ):
			if self.quit_early:
				self.Finished.emit()
				return True
			time.sleep( 2 )
			QtCore.QCoreApplication.processEvents()
		self.data_gathered = False
		return False

	def Run( self ):
		for temperature in self.temperatures_to_measure:
			for device_index in range( len(self.device_config_data["Negative Pad"]) ):
				expected_data = ["Negative Pad","Positive Pad","Device Area (um^2)","Device Perimeter (um)", "Device Location"]
				neg_pad, pos_pad, area, perimeter, location = (self.device_config_data[key][device_index] for key in expected_data)
				meta_data = dict( sample_name=self.sample_name, user=self.user, temperature_in_k=temperature, device_area_in_um2=area,
					 device_location=location, device_perimeter_in_um=perimeter, measurement_setup="LN2 Dewar" )

				self.Temperature_Change_Requested.emit( temperature )
				self.Pad_Change_Requested.emit( int(neg_pad), int(pos_pad) )
				if self.Wait_For_Temp_And_Pads():
					self.Finished.emit()
					return

				print( "Starting Measurement at {} K on pads {} and {}".format( temperature, neg_pad, pos_pad ) )
				self.data_collection_callback = lambda x_data, y_data : self.Sweep_Part_Finished( x_data, y_data, sql_type=self.sql_type, sql_conn=self.sql_conn, meta_data=meta_data )
				self.measurementRequested_signal.emit( self.v_start, self.v_end, self.v_step )
				if self.Wait_For_Data():
					self.Finished.emit()
					return

		print( "Finished Measurment" )
		self.Finished.emit()

	def Collect_Data( self, x_data, y_data ):
		self.data_collection_callback( x_data, y_data )
		self.data_collection_callback = lambda x_data, y_data : None

	def Pads_Ready( self, pads, is_reversed ):
		self.pads_ready = True
		self.pads_are_reversed = is_reversed

	def Temperature_Ready( self ):
		self.temperature_ready = True

	def Quit_Early( self ):
		print( "Quitting Early" )
		self.quit_early = True

	def Sweep_Part_Finished( self, x_data, y_data, sql_type, sql_conn, meta_data ):
		if self.pads_are_reversed:
			x_data = x_data[::-1]
			y_data = y_data[::-1]
		self.data_gathered = True
		Commit_XY_Data_To_SQL( sql_type, sql_conn, xy_data_sql_table="cv_raw_data", xy_sql_labels=("voltage_v","capacitance_f"),
							x_data=x_data, y_data=y_data, metadata_sql_table="cv_measurements", **meta_data )
