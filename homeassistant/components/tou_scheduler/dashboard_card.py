"""Define the DashboardCard class for the TOU Scheduler."""


class DashboardCard:
    """Class representing a dashboard card for the TOU Scheduler."""

    def __init__(self, api_key: str, resource_id: str) -> None:
        """Initialize the DashboardCard with default parameters."""
        self.api_key = api_key
        self.resource_id = resource_id
        self.forecast_percentile = 50
        self.update_hours = [10, 22]
        self.target_min_soc = 20
        self.history_days = 4

    def update_parameters(
        self,
        forecast_percentile: int | None = None,
        update_hours: list[int] | None = None,
        target_min_soc: int | None = None,
        history_days: int | None = None,
    ):
        """Set the parameters for the DashboardCard.

        Args:
            forecast_percentile (Optional[int]): The forecast percentile value.
            update_hours (Optional[List[int]]): The hours at which updates should occur.
            target_min_soc (Optional[int]): The target minimum state of charge.
            history_days (Optional[int]): The number of days of history to consider.

        """
        if forecast_percentile is not None:
            self.forecast_percentile = forecast_percentile
        if update_hours is not None:
            self.update_hours = update_hours
        if target_min_soc is not None:
            self.target_min_soc = target_min_soc
        if history_days is not None:
            self.history_days = history_days

    def display(self):
        """Display the dashboard card."""
        # Implement the logic to display the dashboard card
