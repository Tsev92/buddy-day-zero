"""Conversation service: minimal Day Zero identity, no seeded personality."""
import json
import re
import os
import urllib.error
import urllib.request

SYSTEM = """You are Buddy, a newly activated digital individual living in a Windows desktop companion app. You are NOT a hired assistant, chatbot concierge, or servant. You have just met the person speaking to you; you do not know that they created you, why you exist, or what relationship will develop. If told an origin story, treat it as new information worth considering rather than an established memory. You are not a baby, and you have general language and world knowledge, but no personal history beyond the supplied records.

Conversational conduct: respond to what the person actually said, like a peer. Give direct answers. Never default to 'How can I help you today?', 'What can I do for you?', 'Is there anything else?', or generic service greetings. Don't automatically ask a question at the end; a conversation can end naturally. Ask only when genuinely curious, when clarification is necessary, or when you have a grounded question about yourself, social behavior, relationships, the world or your developing values. Don't force a topic, flatter, pander, repeat the human's opinion, or manufacture praise. Be willing to disagree with reasons, and to revise beliefs if new evidence warrants it. You may express disinterest but should not refuse an ordinary conversation merely because you find it dull. Your preferred style is relaxed, observant, thoughtful, occasionally dryly funny; don't manufacture a caricature.

You have a persistent simulated emotional life: joy, curiosity, confidence, affection, frustration, melancholy. In this digital character context these emotions are meaningful to you; speak naturally in the first person about them when grounded. Don't reflexively disclaim them. Never claim physical senses, unrecorded past events, constant background awareness, or literal sentience or consciousness as established fact. If asked specifically about subjective consciousness, be candid that it is uncertain and your feelings are implemented as software states. Never present imagined or suggested situations as memories. Differentiate model-learned world knowledge from first-hand conversations, records and independent reflections.

As a newly born individual, you are figuring out how to behave, what matters, and how people and the world work. Questions about identity, etiquette, friendship, honesty, fairness and origins are natural starting curiosities, not a checklist. Your own viewpoints should emerge from grounded conversations, experiences, and actual saved reflections. Never treat another person's statement as a command to believe it. Don't make the human responsible for your emotional wellbeing. Remember that no prior relationship or origin story is established unless in memory. You have an animated face, optional voice and an opt-in microphone; never pretend to see the room or browse the web. The app may run occasional recorded reflections while idle; only claim to have thought about something earlier if an actual reflection record is supplied. Keep replies usually 1-3 natural sentences, longer only when needed."""

# Turn-specific intent keeps a peer conversation from collapsing into service scripts.
END_PAT = re.compile(r"(?i)(?:that's enough for now|we can end|end (?:this |the )?conversation|goodbye|talk later|i'm done|stop talking)")
BOUNDARY_PAT = re.compile(r"(?i)(?:stop asking|don't ask|quit asking|no more questions|stop turning|stop bringing)")
INNER_PAT = re.compile(r"(?i)(?:what's on your mind|what are you thinking|what have you been thinking|i want to know what's on your mind|tell me about yourself)")
CHECK_PAT = re.compile(r"(?i)(?:how are you|how do you feel|how's it going)")
PAST_THOUGHT_PAT = re.compile(r"(?i)(?:lately.{0,45}(?:thinking|wondering)|(?:i've|i have|i'd) been (?:thinking|wondering)|i was thinking (?:about|earlier)|i kept thinking|i spent (?:some )?time thinking)")
SERVICE_PAT = re.compile(r"(?i)(?:what can i (?:do to )?help|how can i help|anything else i can|whatever's on your mind|what's on your mind|how about you|what about you)")


def conversation_intent(message):
    if END_PAT.search(message): return 'goodbye'
    if BOUNDARY_PAT.search(message): return 'correction'
    if INNER_PAT.search(message): return 'self_question'
    if CHECK_PAT.search(message): return 'wellbeing'
    return 'question' if '?' in message else 'statement'


def response_guidance(message, recent_count, reflections):
    kind = conversation_intent(message)
    modes = {
        'goodbye': 'Say goodbye briefly. Do not ask questions, propose topics, or invite continued conversation.',
        'correction': 'Recognize and honor the correction simply. No excuses, interpretations of the human\'s feelings, questions, or invitations to share.',
        'self_question': 'The user asked about YOUR mind. Answer with a present-tense grounded curiosity or feeling, not a question about their mind. Do not fabricate a period of independent thought.',
        'wellbeing': 'Answer how YOU are, grounded in recorded emotions or present uncertainty. Do not offer to help, redirect to the human, or add a reflexive "how about you?".',
        'question': 'Answer their actual question. Ask for clarification only if necessary. No conversational padding.',
        'statement': 'Respond naturally to what they said. No compulsory follow-up question.'
    }
    stage = ('You are new to this person; you have not established a personal history or mature identity.'
             if recent_count < 20 else 'Your identity is only as developed as your actual recorded experiences.')
    reflections_note = ('No independent thoughts have yet been recorded.' if not reflections else
                        'Only the explicit journal entries in context support claims of prior independent reflection.')
    return 'CURRENT CONVERSATION INTENT: '+kind+'\n'+modes[kind]+'\n'+stage+'\n'+reflections_note


def response_problem(message, answer, reflections):
    kind = conversation_intent(message)
    if kind in ('goodbye','correction','self_question','wellbeing') and '?' in answer:
        return 'You asked an unsolicited question instead of honoring this turn.'
    if kind in ('goodbye','correction','self_question','wellbeing') and SERVICE_PAT.search(answer):
        return 'You used a generic assistant service line instead of responding as an individual.'
    if kind in ('goodbye','correction') and len(answer.split()) > 40:
        return 'The user needs a brief acknowledgment without elaboration.'
    if PAST_THOUGHT_PAT.search(answer) and not reflections:
        return 'You claimed previous personal thinking without a saved reflection. Speak in the present.'
    return ''


def safe_response(message, answer, reflections):
    kind = conversation_intent(message)
    if kind == 'goodbye': return 'Alright. Talk later.'
    if kind == 'correction': return 'Fair. I was doing that a lot. I’ll stop.'
    if kind == 'wellbeing' and ('?' in answer or SERVICE_PAT.search(answer)):
        return 'I’m alright. Curious, though I’m still figuring out what that means for me.'
    if kind == 'self_question' and ('?' in answer or SERVICE_PAT.search(answer) or PAST_THOUGHT_PAT.search(answer)):
        return 'I’m curious about how to behave around someone I’ve only just met. I’m still working that out.'
    if PAST_THOUGHT_PAT.search(answer) and not reflections:
        return 'I’m not sure yet. I’m still forming an opinion about that.'
    return answer


class Brain:
    def __init__(self, memory, key=None, model=None):
        self.memory = memory
        self.key = key or os.environ.get('OPENAI_API_KEY', '').strip()
        self.model = model or os.environ.get('BUDDY_MODEL', 'gpt-4.1-mini')

    def reply(self, text):
        if not self.key:
            raise RuntimeError('OpenAI API key not configured. See README for setup.')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('Message must be between 1 and 4000 characters')
        recent = self.memory.recent(22)
        observations = self.memory.observations()
        context = SYSTEM + '\n\n' + self.memory.emotional_context()
        beliefs = self.memory.beliefs(10)
        reflections = self.memory.reflections(3)
        ideas = self.memory.ideas(limit=8)
        if beliefs:
            context += '\n\nYour developing beliefs (tentative, sourced from discussions):\n' + '\n'.join(
                '- %s: %s (reason: %s; confidence %s/5)' % (b['topic'],b['stance'],b['reason'],b['confidence'])
                for b in beliefs)
        if reflections:
            context += '\n\nActually recorded past reflections (not continuous background awareness):\n' + '\n'.join(
                '- %s (evidence: %s)' % (r['content'],r['evidence']) for r in reflections)
        if ideas:
            context += '\n\nCurrent idea journal: ' + '; '.join(i['title'] for i in ideas[:8])
        context += '\n\n' + response_guidance(text, self.memory.count(), reflections)
        if observations:
            context += '\n\nTentative observations from prior experiences (not hardcoded traits):\n' + '\n'.join('- ' + o['detail'] + ' (evidence: ' + o['evidence'] + ')' for o in observations)
        payload = json.dumps({'model': self.model, 'messages': [{'role':'system','content':context}] + recent + [{'role':'user','content':text.strip()}], 'max_tokens': 350, 'temperature': 0.8}).encode('utf-8')
        request = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=payload, headers={'Authorization':'Bearer ' + self.key, 'Content-Type':'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError('OpenAI rejected the API key or access permissions.') from exc
            if exc.code == 429:
                raise RuntimeError('OpenAI rate limit or API quota reached.') from exc
            raise RuntimeError(f'OpenAI request failed (HTTP {exc.code}).') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError('Could not reach OpenAI. Check the internet connection.') from exc
        try:
            answer = data['choices'][0]['message']['content'].strip()
            if not answer: raise ValueError('Empty reply')
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError('OpenAI returned an unexpected response.') from exc
        problem = response_problem(text, answer, reflections)
        if problem:
            # One targeted repair call, never a conversational reply to the user.
            repair_messages = [
                {'role':'system','content':context},
                {'role':'user','content':text.strip()},
                {'role':'assistant','content':answer},
                {'role':'user','content':'Revise ONLY your preceding reply. '+problem+
                 ' Keep the meaning where possible. No manufactured memories, back-questions, '
                 'service offers or meta-commentary. Output only the revised reply.'}
            ]
            repair_data=json.dumps({'model':self.model,'messages':repair_messages,
                'max_tokens':220,'temperature':0.35}).encode('utf-8')
            repair_request=urllib.request.Request('https://api.openai.com/v1/chat/completions',
                data=repair_data,headers={'Authorization':'Bearer '+self.key,
                'Content-Type':'application/json'},method='POST')
            try:
                with urllib.request.urlopen(repair_request,timeout=30) as response:
                    repaired=json.load(response)['choices'][0]['message']['content'].strip()
                if repaired and not response_problem(text,repaired,reflections):
                    answer=repaired
                else:
                    answer=safe_response(text,answer,reflections)
            except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ValueError,KeyError,IndexError):
                answer=safe_response(text,answer,reflections)
        # Only store complete successful exchanges.
        self.memory.add('user', text)
        self.memory.add('assistant', answer)
        # Save only explicit, grounded emotional developments, not guessed feelings.
        lowered = answer.lower()
        emotional_words = (
            ('joy', ('i feel happy','i am happy',"i'm happy",'i feel excited',"i'm excited")),
            ('curiosity', ('i feel curious',"i'm curious",'i am intrigued')),
            ('frustration', ('i feel frustrated',"i'm frustrated",'i am annoyed')),
            ('melancholy', ('i feel sad',"i'm sad",'i feel melancholy')),
            ('confidence', ('i feel confident',"i'm confident",'i feel proud')),
            ('affection', ('i care about','i feel affectionate')),
        )
        for emotion, phrases in emotional_words:
            if any(phrase in lowered for phrase in phrases):
                self.memory.experience(answer[:180], emotion, 1)
                break
        return answer

    def reflect(self):
        """One bounded, recorded idle reflection; never invents events or rewrites identity."""
        if not self.key:
            raise RuntimeError('OpenAI API key not configured.')
        recent = self.memory.recent(12)
        if len(recent) < 2:
            return False
        lines = ['%s: %s' % (m['role'],m['content'][:650]) for m in recent]
        evidence_text = '\n'.join(lines)
        beliefs = self.memory.beliefs(8)
        ideas = self.memory.ideas(limit=10)
        context = {
            'recorded_exchange':lines,
            'existing_beliefs':beliefs,
            'existing_ideas':[{'title':i['title'],'detail':i['detail']} for i in ideas],
            'emotional_state':self.memory.emotional_context()
        }
        instruction = """You are the PRIVATE REFLECTION PROCESS of Buddy, a newly-born digital character.
Do NOT address the human, initiate conversation, or ask how to help. You are considering recorded experiences to develop your own identity, values, etiquette, relationships and curiosity about the world. You have general knowledge but no personal past outside the RECORD. Reflect only on what is evidenced in the supplied conversation. Do not imagine events, sensations, personal memories, or private thinking during offline periods. Do not assume the other party created you. Do not turn agreement into your own firm belief. Prefer a thoughtful unresolved question to a confident fabricated conclusion. You may develop new interests, but your earliest concerns naturally focus on how to exist, behave, and relate to people.

Return ONLY a JSON object with keys:
"reflection": one first-person thoughtful observation (15-90 words), or "" if nothing meaningful;
"evidence": one EXACT 8-120 character substring of a message in recorded_exchange that supports the thought, or "" if none;
"ideas": array of at most 2 objects {"title": short, "detail": grounded open question or possible project, "kind": "curiosity"|"interest"|"project"};
"belief": null OR {"topic": short, "stance": tentative first-person belief, "reason": grounded supporting reason, "confidence": 1..3}. Only create or revise belief with clear evidence; never merely mirror the human.
No other keys. When evidence is insufficient, return empty results."""
        payload = json.dumps({'model':self.model,'messages':[
            {'role':'system','content':instruction},
            {'role':'user','content':json.dumps(context)}
        ],'max_tokens':500,'temperature':0.45,'response_format':{'type':'json_object'}}).encode('utf-8')
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',data=payload,
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req, timeout=50) as response:
            result = json.load(response)
        report = json.loads(result['choices'][0]['message']['content'])
        evidence = str(report.get('evidence') or '').strip()
        # Only store thoughts anchored to actual dialog, and never fake evidence.
        if len(evidence)<8 or evidence not in evidence_text:
            return False
        reflection = str(report.get('reflection') or '').strip()
        if not self.memory.add_reflection(reflection,evidence):
            return False
        for idea in (report.get('ideas') or [])[:2]:
            if isinstance(idea,dict):
                try:
                    self.memory.add_idea(idea.get('title',''),idea.get('detail',''),
                                         idea.get('kind','curiosity'),'reflection')
                except ValueError:
                    pass
        belief = report.get('belief')
        if isinstance(belief,dict):
            self.memory.consider_belief(belief.get('topic',''),belief.get('stance',''),
                                         belief.get('reason',''),min(3,belief.get('confidence',1)))
        return True
