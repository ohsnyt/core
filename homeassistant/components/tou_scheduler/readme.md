“””
The TOU Scheduler for home assistant is comprised of three components:
1. Visual user interface (dashboard card)
2. API backend that interacts with the visual interface
3. Inverter or other off-peak charging system

I assume that an inverter API will also include opportunity to provide pv, load, grid and possibly generator sensor information. It will have the ability to set Time of Use parameters.
Solar Assistant may fill the role of the inverter API

This visual user interface helps a user manage Time of Use optimization. It works together with a Home Assistant custom component API which monitors pv generation, load usage and efficiency parameters stored in Home Assistant. It also gathers insolation forecasts from Solcast in order to predict tomorrow’s estimated PV generation. These factors taken together automatically set the off-peak grid charging of the battery storage system to supplement estimated PV for the next day.

The user interface allows the user to set key information including:
        Solcast api_key
        Solcast resource_id
        Solcast forecast desired percentile (10-90%) to use for calculations
	A set of 1-4 hours when the user wants to request updated forecast information from solcast.com. Default hours are 10am and 10pm
	The desired target minimum state of charge for midnight
	The desired number of days to use when calculating estimated future load requirements.

The user interface displays information including:
        Current battery State of Charge
	Automatically calculated off-peak State of Charge target for today
	Automatically calculated off-peak State of Charge target for tomorrow
	Manually set off-peak State of Charge target (grey if in automatic mode)
	Whether the system is in automatic or manual mode
	Number of days remaining for using manual SoC target


The user interface also allows the user to select the device that controls off-peak charging. The only currently implemented device is the Sol-Ark inverter.

The interface also allows the user to choose which home-assistant sensors are to be used to gather pv generation, load usage, grid import, generator import parameters.

The integration calculates inverter efficiency based on load power used divided by all power input sources, over the lifetime of the statistics.
The integration calculated average hourly loads based on the user specified number of days of history. (Default is 4 days).
The integration calculates hourly shading based on the comparison of PV generation to estimated PV during full sun, assuming the battery State of Charge is less than 95% (thus PV is not restricted by inability to use generated power)
“””
