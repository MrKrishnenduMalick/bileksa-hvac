import { loadPyodide } from "pyodide";
import { readFileSync } from "node:fs";
const py = await loadPyodide({ indexURL: "/tmp/pyo/pyodide/" });
await py.loadPackage(["fastapi", "sqlalchemy", "micropip", "pydantic", "cryptography"], { messageCallback: () => {} });
for (const w of ["PyJWT-2.10.1-py3-none-any.whl", "phonenumbers-9.0.44-py2.py3-none-any.whl"]) {
  py.FS.writeFile(`/tmp/${w}`, readFileSync(`wheels/${w}`));
}
await py.runPythonAsync(`import micropip; await micropip.install(["emfs:/tmp/PyJWT-2.10.1-py3-none-any.whl","emfs:/tmp/phonenumbers-9.0.44-py2.py3-none-any.whl"])`);
py.FS.writeFile("/home/pyodide/workload.py", readFileSync("workload.py"));
const t0 = process.cpuUsage();
const out = await py.runPythonAsync(`import sys; sys.path.insert(0,"/home/pyodide"); import workload; await workload.main()`);
console.log("pyodide", out);
