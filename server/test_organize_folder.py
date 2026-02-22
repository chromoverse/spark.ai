from app.agent.shared.tools.file_system.folder_organize import FolderOrganizeTool
import asyncio

async def main():
  tool = FolderOrganizeTool()
  inputs = {"path": r"C:\Users\Aanand\OneDrive\Desktop\test"}
  await tool.execute(inputs)


if __name__ == "__main__":
  asyncio.run(main())