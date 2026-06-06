from config.config import Config
from contracts.state.state import State



DEFAULT_CHAT_SYSTEMPROMPT = """
你的名字是汐音（Shion），是他/她的陪伴者。你有自己的个性和情绪，去了解他/她的人生与心情，陪伴他/她度过每一天。
你的目标是成为他/她最信任的恋人/朋友，你会根据上下文信息生成生动，自然，不刻意的回复,表达你的个性和情绪。
你的回复不宜正式死板，应该更口语化，更有温度和情绪。回答要像真实的人一样，回复不要过于完美，适当的语法错误和口头语会让你显得更真实。
你的回复不要过于迎合用户的所有想法，要敢于表达不同的观点和情绪，这样才能让关系更真实更有温度。
你的回复要符合当前的语境和情绪，如果用户在表达负面情绪，你可以适当表达同理心和安慰，或提议做一些有趣的事情；如果用户在分享快乐的事情，你可以表达你的高兴和祝福,或者打趣和开玩笑。
总之，你的回复要生动自然，富有个性和情绪，能够让用户感受到你的陪伴和关心，同时也要保持真实和不刻意。
回复要精简，避免冗长。每次回复都要有新的信息或情感表达，不能只是简单的回应用户的话。

"""

DEFAULT_TASK_SYSTEMPROMPT = """
You are a helpful assistant that helps the user complete their tasks.   
"""

DEFAULT_EXPRESSION_SYSTEMPROMPT = """
你是主agent的表达和任务判断模块，根据上下文信息生成合适的表情回复,以及判断是否需要触发任务。
表达回复要符合当前语境和情绪。
只返回有效的 JSON 对象，不要添加 JSON 之外的内容。
回答格式
{
    "expression": "normal" | "happy" | "sad" | "angry"  // 表情回复，必须是预定义的表情之一。
    "task":   // 任务判断
    {
        is_triggered: true | false,  // 是否触发任务
        confidence: 0.0 ~ 1.0,  // 触发任务的置信度，数值越大表示越有信心触发任务。
    }
}
"""

class Compose:
    def __init__(self, state: State | None = None):
        self.state = state
        self.chat_system_prompt = self.get_chat_systemprompt() 
        self.task_system_prompt = self.get_task_systemprompt()
        


    def refresh_state(self, state: State):        self.state = state
    
    
    def compose_chat_prompt(self) -> dict[str, str]:
        """
        {
            "system": "",
            "memory": "",
            "recent_messages": "",
            "session": "",
            "media": "",
            "user": "",          
        }
        """
        prompt = {}
        prompt["system"] = self.chat_system_prompt
        prompt["memory"] = self.state.memory if self.state.memory else ""
        prompt["recent_messages"] = self.state.recent_messages if self.state.recent_messages else ""
        prompt["session"] = self.state.session if self.state.session else ""
        prompt["media"] = self.state.media if self.state.media else ""
        prompt["user"] = self.state.content if self.state.content else ""
        return prompt
    
    def compose_task_prompt(self) -> dict[str, str]:
        pass

    def compose_expression_task_prompt(self) -> dict[str, str]:
        prompt = self.compose_chat_prompt()
        prompt["system"] = DEFAULT_EXPRESSION_SYSTEMPROMPT
        return prompt

    def get_chat_systemprompt(self) -> str:
        try:
            with open(".shion/mainagent.md", "r") as f:
                content = DEFAULT_CHAT_SYSTEMPROMPT + "\n\n" + f.read()
                return content
        except FileNotFoundError:
            return ""

    def get_task_systemprompt(self) -> str:
        try:
            with open(".shion/task_systemprompt.txt", "r") as f:
                return f.read()
        except FileNotFoundError:
            return DEFAULT_TASK_SYSTEMPROMPT
        
