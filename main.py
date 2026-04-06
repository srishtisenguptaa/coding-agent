# from modules.github_reader import GitHubReader
# from modules.code_parser import CodeParser
# from modules.patch_generator import PatchGenerator
# from modules.sandbox_executor import SandboxExecutor

# reader = GitHubReader()
# parser = CodeParser()
# patcher = PatchGenerator()
# executor = SandboxExecutor()

# # Fetch issue
# data = reader.read_issue("psf/requests", 6361)

# # Parse code
# parsed = parser.parse(data)

# # Generate patches
# patches = patcher.generate(data, parsed)

# # Run patches in Docker sandbox
# results = executor.run(data, patches)

# print("\n========== SANDBOX RESULTS ==========")
# for r in results:
#     status = "✓ PASSED" if r.success else "✗ FAILED"
#     print(f"\n{status} — {r.patch.class_name}")
#     if r.success:
#         print(r.test_output)
#     else:
#         print(f"Error: {r.error_output[-300:]}")


from modules.agent import run_agent

if __name__ == "__main__":
    summary = run_agent("psf/requests", 7188)