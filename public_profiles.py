"""Public introductions are separate from the instructions used by the AI."""
import json

LIMITS = {'intro': 300, 'personality': 160, 'likes': 160, 'basics': 400, 'details': 1200, 'memories': 1200}


def normalize(value):
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise ValueError('公開プロフィールの形式が正しくありません')
    result = {}
    for key, limit in LIMITS.items():
        text = value.get(key, '')
        if not isinstance(text, str) or len(text.strip()) > limit:
            raise ValueError(f'公開プロフィールの{key}は{limit}文字以内で入力してください')
        result[key] = text.strip()
    return result


def legacy_introduction(profile):
    # Only explicitly labelled facts may migrate; never copy the AI prompt wholesale.
    lines = [line.strip() for line in profile.splitlines() if line.strip()]
    def fact(label):
        for i, line in enumerate(lines):
            if line == label and i + 1 < len(lines):
                value = lines[i + 1]
                if len(value) <= 80 and value not in ('キャラクター設定', 'ビジュアルコンセプト'):
                    return value
        return ''
    occupation, personality = fact('職業'), fact('性格')
    basics = [f'{key}：{fact(key)}' for key in ('愛称', '年齢', '誕生日', '身長') if fact(key)]
    return normalize(dict(intro='。'.join(item for item in (occupation, personality) if item),
                          personality=personality, likes=fact('好きなもの'), basics='\n'.join(basics), details=''))


def read(raw, legacy=''):
    if not raw:
        return legacy_introduction(legacy)
    try:
        return normalize(json.loads(raw))
    except (ValueError, TypeError):
        return normalize({})
