from app.agent.shared.automation.whatsapp.whatsapp_automation import WhatsAppAutomation

async def main():
  wa = await WhatsAppAutomation().create()
  # wa.send_file("Daddy",    r"C:\Users\Aanand\OneDrive\Desktop\Chromoverse_Vyoma.pdf", caption="Here's the file!")
  # wa.send_photo("Daddy",   r"C:\Users\Aanand\OneDrive\Desktop\blob.jpg",            caption="Check this out!")
  # wa.send_message("Daddy", "Testing messages!")
  wa.audio_call("Daddy")
  # wa.video_call("Daddy")

if __name__ == "__main__": 
  import asyncio
  asyncio.run(main())