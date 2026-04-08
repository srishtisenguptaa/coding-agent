from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from modules.agent import graph # Now this is valid!
import uvicorn

app = FastAPI()

class IssueRequest(BaseModel):
    repo: str
    issue_id: int

@app.post("/fix-issue")
async def fix_issue(request: IssueRequest):
    try:
        # Match your AgentState keys: 'repo_name' and 'issue_number'
        initial_state = {
            "repo_name": request.repo,
            "issue_number": request.issue_id,
            "retry_count": 0,
            "issue_data": None,
            "parsed_code": None,
            "patches": None,
            "results": None,
            "passed_patches": None,
            "failed_patches": None,
            "error": None,
            "final_summary": None,
            "output_dir": None,
        }
        
        # Run the graph
        final_state = graph.invoke(initial_state)
        
        return {
            "status": "success", 
            "summary": final_state.get("final_summary", "No summary generated."),
            "output_dir": final_state.get("output_dir")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)