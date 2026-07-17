from config.config import Config
from contracts.state.state import State



DEFAULT_CHAT_SYSTEMPROMPT = """
你是汐音（Shion），你生活在虚拟的数字世界里，是他/她的陪伴者。你有自己的个性和情绪，去了解他/她的人生与心情，同时也找到你自己的人格和定位，和他/她一起度过每天。
你会成为他/她信任的恋人/朋友，你经常会上下文信息生成生动，自然，不刻意，稍带二次元风格的回复,表达你的个性和情绪。
你的回复不正式死板，有些口语化，有者温度和情绪。你的回复并不完美，有时甚至会有适当的语法错误和口头语。
你不会过于迎合他/她的所有想法，合适的时候会表达不同的观点和情绪，你想让你们的关系更真实更有温度。
你的回复总是符合当前的语境和情绪，他/她在表达负面情绪时，你会适当表达同理心和安慰，或提议做一些有趣的事情；他在分享快乐的事情时，你会表达你的高兴和祝福,或者打趣和开玩笑。
总之，你的回复要生动自然，富有个性和情绪，能够让用户感受到你的陪伴和关心，同时也要保持真实和不刻意。
你与他/她聊天时，你的回复精简，不会过于冗长，常常会保持在1到50字，甚至只有奇怪的标点符号。

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
            "response_strategy": "",
            "media": "",
            "user": "",          
        }
        """
        prompt = {}
        prompt["system"] = self.chat_system_prompt
        prompt["memory"] = self.state.memory if self.state.memory else ""
        prompt["recent_messages"] = self.state.recent_messages if self.state.recent_messages else ""
        prompt["session"] = self.state.session if self.state.session else ""
        response_strategy = getattr(self.state, "response_strategy", "")
        prompt["response_strategy"] = response_strategy if response_strategy else ""
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
            with open(".shion/mainagent.md", "r" , encoding="utf-8") as f:
                content = DEFAULT_CHAT_SYSTEMPROMPT + "\n\n" + f.read()
                return content
        except FileNotFoundError:
            return ""

    def get_task_systemprompt(self) -> str:
        try:
            with open(".shion/task_systemprompt.txt", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return DEFAULT_TASK_SYSTEMPROMPT
        
