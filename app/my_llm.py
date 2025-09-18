from transformers import AutoTokenizer, AutoModelForCausalLM, GenerationConfig

class MyLLM:
    def __init__(self, MODEL_DIR="Qwen/Qwen2.5-14B-Instruct"):
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR,
            dtype="auto",
            device_map="auto"
        )
        try:
            self.gen_config = GenerationConfig.from_pretrained(MODEL_DIR)
        except Exception:
            self.gen_config = None

    def chat(self, system_prompt, user_prompt, max_new_tokens=1024):
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                chat_template="""{% for message in messages %}
<|{{ message['role'] }}|>
{{ message['content'] }}
{% endfor %}
<|assistant|>
"""
            )
            model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=1024 ,
                do_sample=False,
                repetition_penalty=1.0
            )
            response = self.tokenizer.decode(generated_ids[0][model_inputs["input_ids"].shape[-1]:])
            return {"response": response}

            generated_ids = [
                output_ids[len(input_ids):] 
                for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
            ]
            response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]

            return {"response": response}

        except Exception as e:
            return {"error": str(e)}