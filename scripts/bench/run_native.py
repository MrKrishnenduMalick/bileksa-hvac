import asyncio, sys
sys.path.insert(0, ".")
import workload
print("native", asyncio.run(workload.main()))
