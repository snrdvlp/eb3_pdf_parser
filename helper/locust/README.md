## **Instructions to Run Locust**

### **1. Install Python and Locust**

Make sure Python 3 is installed. Then install Locust:

```bash
pip install locust
```

### **2. Run Locust**

Open a terminal in the folder containing `locustfile.py` and run:

```bash
locust -f locustfile.py --host https://pdf-parser.ebthree.com
```

* `--host` → points to **your server** (use HTTPS).
* This starts a **web UI** at `http://localhost:8089`.

---

### **3. Open the Web UI**

* Open a browser and go to:

```
http://localhost:8089
```

* Configure the **number of users(i.e., 30)**, **spawn rate(i.e., 3)**, and start the test.

---

