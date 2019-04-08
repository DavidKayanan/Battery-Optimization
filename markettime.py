"""The purpose of this module is to implement market time formats. Currently, only the CAISO format is implemented.
These formats must provide at least the ff:

	TimeStamp()             Constructor of the market timestamp class.
	GMT_toMarket()          Method that converts a timestamp in GMT to the format defined by the market.
	Market_toGMT()          Method that converts a timestamp in the market format back to GMT.
	delta_t                 Time resolution as datetime.timedelta
	get_month_ends(year)    Class method that returns  a mapping {mm: (start, end)} where mm is the numeric month
							(1-12), and start, end are the starting and ending market time stamps of month mm.

The time formats should implement DST as necessary, to comply with actual standards.

"""
import datetime

class MarkettimeError(Exception):
	"""Base exception for markettime.py errors."""
	pass


class UndefinedDST(MarkettimeError):
	"""Raised when a DST-observing time handles a date whose year is not defined in the DST period."""
	pass

delta_hr = datetime.timedelta(hours=1)

month_abrv = {
	1: 'Jan',
	2: 'Feb',
	3: 'Mar',
	4: 'Apr',
	5: 'May',
	6: 'Jun',
	7: 'Jul',
	8: 'Aug',
	9: 'Sep',
	10: 'Oct',
	11: 'Nov',
	12: 'Dec'
}
month_abrv_rev = {mmm: num for num, mmm in month_abrv.items()}



def isleapyr(year):
	return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def get_month_enddates(year):
	if isleapyr(year):
		feb_end = 29
	else:
		feb_end = 28

	return {
		1 : 31,
		2 : feb_end,
		3 : 31,
		4 : 30,
		5 : 31,
		6 : 30,
		7 : 31,
		8 : 31,
		9 : 30,
		10: 31,
		11: 30,
		12: 31
	}



class CAISO():
	"""Implements the CAISO market time format. Instances implement the market time at a given jurisdiction (as a GMT
	offset)"""

	class TimeStamp():
		"""Market time stamp. Instances are NOT tied to CAISO instances."""
		# TODO - The TimeStamp class of the various formats should be standardized
		# (just as the methods GMT_toMarket, Market_toGMT are)
		# TODO - On second thought, should have ridden on the datetime.datetime class instead
		# so that the class methods can be used (e.g. add one day)

		def __init__(self, dt: datetime.date, hr: int):
			if not isinstance(dt, datetime.date):
				raise TypeError("Market dt must be of the datetime.date class.")

			if hr=='first':
				hr = 1

			if not isinstance(hr, int):
				raise TypeError("Market hr must be an integer from 1-25.")
			if not 1 <= hr <= 25:
				raise ValueError("Market hr must be an integer from 1-25.")

			# date object
			self.dt = datetime.date(year=dt.year, month=dt.month, day=dt.day)
			# market hour
			self.hr = hr

			# Convenience
			self.year = dt.year
			self.month = dt.month
			self.day = dt.day

			return


		def __repr__(self):
			return "{MM}/{DD}/{YYYY} H{HH}".format(MM=str(self.dt.month).zfill(2),
			                                       DD=str(self.dt.day).zfill(2),
			                                       YYYY=self.dt.year,
			                                       HH=str(self.hr).zfill(2))

	@staticmethod
	def get_month_ends(year):
		"""Returns a dictionary {m: (start, end)}, with m=1 to 12 (months); and with start and end as the first and
		final TimeStamps of the month"""
		enddates = get_month_enddates(year)

		return {mm: (CAISO.TimeStamp(datetime.date(year, mm, 1), hr=1),
		             CAISO.TimeStamp(datetime.date(year, mm, enddates[mm]), hr=24))
		        for mm in range(1,13)}


	def __init__(self, GMToffset, ObserveDST=True, DST_periods=None, delta_t=1):
		"""Initialize the CAISO time of a jurisdiction.

		ARGUMENTS:
			GMToffset       GMT offset in hours [-12, 12]

			ObserveDST      Bool, defaults to True. If True, DST practice is implemented. Need to manually specify
							the DST periods per year.

			DST_periods     Dict {Year : (GMT_Start, GMT_End)}

							where,
								Year        is the year defining the DST period (int)

								GMT_Start   Is the starting hour of DST, in GMT time (i.e. on the GMT date and time
											the clocks are advanced by one hour) ("MMM DD, YYYY Hhh" e.g. 'Jan 01,
											2019 H10' -- 24-hr clock)

								GMT_End     Is the final hour of DST, in GMT time (i.e. the final hour right BEFORE the
											clocks are pushed back by one hour). In CAISO, this is hour 25.
											("MMM DD, YYYY Hhh" -- 24-hr clock)


							Attempts to parse dates in the years not in DST_periods (if ObserveDST) will raise the
							UndefinedDST exception.

			delta_t         Time resolution in hours.

		"""
		if not -12 <= GMToffset <= 12:
			raise ValueError("GMT offset must be within -12 and 12.")

		self.GMToffset = datetime.timedelta(hours=GMToffset)
		self.ObserveDST = ObserveDST
		self.DST_periods = {}
		if DST_periods:
			self.update_DST(DST_periods)

		self.delta_t = datetime.timedelta(hours=delta_t)

		return


	def __repr__(self):
		prms = {'GMToffset': self.GMToffset.days*24 + self.GMToffset.seconds/3600}
		if prms['GMToffset'].is_integer():
			prms['GMToffset'] = int(prms['GMToffset'])

		if self.ObserveDST:
			prms['DSTreport'] = "DST observed in: {}".format(", ".join(str(yr) for yr in self.DST_periods.keys()))
		else:
			prms['DSTreport'] = "DST NOT observed."

		return "CAISO market time at GMT{GMToffset}. {DSTreport}".format(**prms)


	def update_DST(self, DST_periods):
		"""Simple strptime on the string date arguments. This updates the self.DST_periods dictionary"""
		# Todo - can add error checking (verify years are consistent; that dt_ends[0] < dt_ends[1]
		self.DST_periods.update({yr: (datetime.datetime.strptime(dt_ends[0], '%b %d, %Y H%H'),
		                              datetime.datetime.strptime(dt_ends[1], '%b %d, %Y H%H'))
		                         for yr, dt_ends in DST_periods.items()})
		return



	def GMT_toMarket(self, GMT: datetime.datetime):
		"""Convert a GMT time (datetime.datetime) to the CASIO market time (DST-adjusted if applicable)."""
		# --------------------------------------------------------------------------------------- PRELIMS
		if not isinstance(GMT, datetime.datetime):
			raise TypeError("Pls. pass a datetime.datetime object for the GMT time.")

		# --------------------------------------------------------------------------------------- Step 1: GMT offset
		# LOCAL date = GMT date + GMT OFFSET + 1hr(if DST)
		dt_loc = GMT + self.GMToffset
		hr = None

		# --------------------------------------------------------------------------------------- Step 2: Check DST
		# Note: use year of dt_loc (not GMT) to prevent year spill-overs.
		if self.ObserveDST:
			if dt_loc.year not in self.DST_periods:
				raise UndefinedDST(
					"{} is not in self.DST_periods. Pls. include the DST period for this year.".format(GMT.year))


			DST_start, DST_end = self.DST_periods[dt_loc.year]

			# CASE 1: within DST period, but not the final hour
			if DST_start <= GMT < DST_end:
				dt_loc += delta_hr

			# CASE 2: Hr25, final hour of DST (+1hr omitted as it has no effect later on)
			elif GMT == DST_end:
				hr = 25

		# Other cases - outside DST and DST not observed (do nothing)

		if hr is None:
			hr = dt_loc.hour + 1   # This is always true, except for Hr25

		# Only the date properties (y/m/d) of dt_loc are used, so no need to add one hour in Case 2
		return CAISO.TimeStamp(dt_loc, hr)


	def Market_toGMT(self, markettime: TimeStamp):
		"""Convert a CAISO market time to GMT (datetime.datetime, DST-adjusted if applicable)."""
		if not isinstance(markettime, CAISO.TimeStamp):
			raise TypeError("Pls. pass a CAISO.markettime time stamp.")

		# ------------------------------------------------------------------------------------ CASE 1 - Hr 25
		if markettime.hr == 25:
			if markettime.year not in self.DST_periods:
				raise UndefinedDST("Cannot verify Hour 25 due to undefined DST period for year {}. Pls. define "
				                   "this in the CAISO instance.".format(markettime.year))

			# Hr 25 is well-defined per year.
			# To test if Hr 25 is correct, compare the argument with the expected Hr 25.
			expected_h25 = self.GMT_toMarket(self.DST_periods[markettime.year][1])
			if markettime.month == expected_h25.month and markettime.day == expected_h25.day:
				return self.DST_periods[markettime.year][1]
			else:
				raise ValueError("Hr 25 passed does not correspond to that defined in self.DST_periods for the given "
				                 "year.")


		# ------------------------------------------------------------------------------------ CASE 2 - Everything else
		else:
			# This relationship is always true, as long as it's not hr25
			dt_loc = datetime.datetime(year=markettime.year, month=markettime.month, day=markettime.day,
			                           hour=markettime.hr-1)

			# ---------------------------------------------------- 2.1 GMT offset
			# LOCAL date = GMT date + GMT OFFSET + 1hr(if DST)
			dt_GMT = dt_loc - self.GMToffset

			# ---------------------------------------------------- 2.2 DST adjustment
			if self.ObserveDST:
				if dt_loc.year not in self.DST_periods:
					raise UndefinedDST("{} is not in self.DST_periods. Pls. include the DST period for this "
					                   "year.".format(dt_loc.year))

				# First, ASSUME w/in DST
				dt_GMT -= delta_hr

				DST_start, DST_end = self.DST_periods[dt_loc.year]

				# DST_end should not be included in the inequality -- both Hr25 and the succeeding hr (first of
				# winter time) would map to DST_end if -(GMT offset + 1hr). Hr25 is handled above; so DST_end here is
				# NOT part of the DST period.
				if not (DST_start <= dt_GMT < DST_end):
					# Assumption was wrong; revert.
					dt_GMT += delta_hr

			return dt_GMT


	def get_monthsofyear(self):
		""""""



# Predefined market times
CA_time = CAISO(GMToffset=-8, DST_periods={2018: ("Mar 11, 2018 H10", "Nov 04, 2018 H09")})
