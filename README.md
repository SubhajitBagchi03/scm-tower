# 🏭✨ SCM AI Control Tower 🚀
[![License: MIT](https://img.shields.io/badge/License-MIT-pink)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-pink?logo=python&logoColor=white)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-pink?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-pink?logo=next.js&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/SQLite-pink?logo=sqlite&logoColor=white)](https://sqlite.org/)
[![Groq](https://img.shields.io/badge/Groq_API-pink?logo=groq&logoColor=white)](https://groq.com/)
[![Last Commit](https://img.shields.io/github/last-commit/anwexhaa/scm-ai-control-tower?color=pink)](https://github.com/anwexhaa/scm-ai-control-tower)
> Agentic AI for supply chain intelligence — because your supply chain deserves better than a spreadsheet. 💀

SCM AI Control Tower connects the dots your existing tools never could. Delayed shipment + low stock = stockout predicted automatically before it happens. Upload any CSV in any format. Ask your supplier contracts questions in plain English. Get a full executive report in 10 seconds. 🔥

**Live:** [scm-deployedd.vercel.app](https://scm-deployedd.vercel.app)

---

## 🚀 Features & Superpowers

⚡ **Smart CSV Ingestion** — Upload literally any CSV format. No templates, no reformatting. AI maps your weird column headers automatically, detects conflicts field by field, and nothing touches the database without your confirmation.

💥 **Cascade Risk Detection** — The headline feature. When a shipment is delayed the system automatically checks if stock will run out before the restock arrives. If yes — CASCADE RISK: CRITICAL. No other affordable supply chain tool does this automatically.

🤖 **Multi-Agent Intelligence (Supervisor-Judge Architecture)** — Five specialized agents orchestrated by a Supervisor and validated by a Judge:
- 📦 **Inventory Agent** — EOQ, safety stock, reorder point, days until stockout
- 🏪 **Supplier Agent** — Dynamic weighted scoring with LLM contextual reasoning
- 🚚 **Shipment Agent** — Delay risk scoring + cascade detection with LLM reasoning
- 📊 **Report Agent** — KPIs, root cause analysis, 14-day projections, PDF export
- ⚖️ **Judge Agent** — Cross-checks findings for contradictions before presenting to user

📄 **RAG Document & Live Data Intelligence (Ask)** — Single unified query interface. Ask questions in plain English. The system automatically routes to live database queries (stock levels, risks) or searches uploaded PDF documents (contracts, SLAs) returning source citations.

⚙️ **Configurable Business Rules** — No hardcoded magic numbers. Change safety stock Z-scores, EOQ costs, and seasonal multipliers easily via config files or environment variables without touching Python code.

---

## 💡 Why SCM AI Control Tower?

Every system alerts you when stock hits a threshold. Nobody automatically connects a delayed shipment to a future stockout by cross-referencing shipment lead times against current inventory consumption rates in real time.

That's the gap. That's what we built. 🔥

---

## 🧠 Agent Formulas
```python
# Inventory Agent — pure Python, no LLM
EOQ              = √(2 × annual_demand × ordering_cost / holding_cost)
Safety Stock     = 1.645 × std_dev × √lead_time  # 95% service level
Reorder Point    = (avg_daily_consumption × lead_time) + safety_stock
Days to Stockout = current_stock / avg_daily_consumption

# Supplier Agent — weights shift by urgency
Normal:    On-time 35% | Quality 25% | Cost 25% | Reliability 15%
Urgent:    On-time 50% | Quality 25% | Cost 15% | Reliability 10%
Immediate: On-time 60% | Quality 25% | Cost 10% | Reliability  5%
True Cost = base_cost×qty + urgency_premium + carrying_cost + risk_penalty

# Shipment Agent
Delay Risk = (days_overdue×0.4) + (carrier_late_rate×0.3) + (supplier_issue_rate×0.3)
Cascade    = days_of_stock_remaining < lead_time_days → CRITICAL

# Report Agent
Inventory Health = (products_above_reorder / total) × 100
On-Time Rate     = (on_time_shipments / total) × 100
Supplier Health  = avg(on_time×0.5 + quality×0.3 + issue_penalty×0.2) × 100
```

---

## ⚡ Getting Started
```bash
# Backend
cd scm
pip install -r requirements.txt

# .env
GROQ_API_KEY=gsk_your_groq_api_key
DATABASE_URL=sqlite+aiosqlite:///./scm_db.db

python main.py
```
```bash
# Frontend
cd scm_frontend
npm install

# .env.local
NEXT_PUBLIC_API_BASE=http://localhost:8000

npm run dev
```

---

## 🛠️ Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | Next.js, TypeScript, vanilla CSS |
| Backend | FastAPI, Python 3.11 |
| Database | SQLite + SQLAlchemy async (`aiosqlite`) |
| Vector Store | ChromaDB (persistent) |
| LLM | Groq API (`openai/gpt-oss-120b`) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| PDF Generation | ReportLab |

---

*Built with Python, FastAPI, Next.js, Groq, SQLite, and ChromaDB.* 🔥
