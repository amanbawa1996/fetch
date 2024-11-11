from uagents import Protocol, Model

# Data model to hold the collected data
class CollectedData(Model):
    data: dict

# Protocol to facilitate data sharing between agents
data_sharing_proto = Protocol(name="data_sharing_proto", version=1.0)
