from datetime import datetime


class SimulationClock:
    """
    Central time source for GreyLine.

    Live mode:
    - returns real UTC time.

    Simulation mode:
    - returns the injected simulated timestamp.
    """

    _simulation_mode = False
    _simulated_time = None

    @classmethod
    def enable_simulation(cls, simulated_time):
        if isinstance(simulated_time, str):
            simulated_time = datetime.fromisoformat(simulated_time)
        cls._simulation_mode = True
        cls._simulated_time = simulated_time

    @classmethod
    def disable_simulation(cls):
        cls._simulation_mode = False
        cls._simulated_time = None

    @classmethod
    def now(cls):
        if cls._simulation_mode and cls._simulated_time is not None:
            return cls._simulated_time
        return datetime.utcnow()

    @classmethod
    def isoformat(cls):
        return cls.now().isoformat()

    @classmethod
    def status(cls):
        return {
            "engine": "SimulationClock",
            "simulation_mode": cls._simulation_mode,
            "current_time": cls.isoformat(),
            "status": "SIMULATION_CLOCK_READY",
        }
