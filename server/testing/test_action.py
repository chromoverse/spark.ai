from app.services.actions.action_dispatcher import dispatch_action

def test():
  print("dispatching the action")
  dispatch_action("open_app", 
  {"app_name": "notepad", 
   "content": "Hello there its me siddhant yadav . currently builfing an ai assistant"
   })

test()