"""
DISC-тест психотипа продавца для Telegram.

Бот задаёт 20 вопросов (метод DISC / Марстон: Красный-Жёлтый-Зелёный-Синий),
считает баллы по 4 психотипам, определяет два ведущих психотипа
и выдаёт человеку персональный разбор (плюсы, минусы, рекомендации),
а затем предлагает перейти в Telegram-канал или на обучение.

Как это работает технически:
- python-telegram-bot (async, v21+), long polling (не нужен вебхук/домен)
- Состояние теста и результаты каждого пользователя хранятся через
  PicklePersistence (context.user_data) в файле PERSISTENCE_PATH —
  переживает перезапуск процесса бота. На Railway/Heroku-подобных
  платформах с эфемерной файловой системой это НЕ переживает передеплой
  без подключённого постоянного диска (volume) — для этого нужно
  подключить volume и указать PERSISTENCE_PATH внутри него, либо
  впоследствии перейти на SQLite/внешнюю БД.
- Все настройки (токен, ссылки, тексты кнопок) берутся из переменных
  окружения — см. .env.example
"""

import logging
import os
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    PicklePersistence,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# НАСТРОЙКИ (из переменных окружения)
# --------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_URL = os.environ.get("CHANNEL_URL", "https://t.me/your_channel")
COURSE_URL = os.environ.get("COURSE_URL", "https://your-course-link.example")
CHANNEL_BUTTON_TEXT = os.environ.get("CHANNEL_BUTTON_TEXT", "📣 Подписаться на канал")
COURSE_BUTTON_TEXT = os.environ.get("COURSE_BUTTON_TEXT", "🎓 Записаться на обучение")
PERSISTENCE_PATH = os.environ.get("PERSISTENCE_PATH", "bot_persistence.pickle")

# Финальный платный оффер (полный профиль DISC + код мотивации). Пока без
# автоматической оплаты — ADMIN_CONTACT_URL ведёт на личку/канал для связи;
# если не задан, бот просто попросит написать в личные сообщения.
FULL_REPORT_PRICE = os.environ.get("FULL_REPORT_PRICE", "[цена уточняется]")
ADMIN_CONTACT_URL = os.environ.get("ADMIN_CONTACT_URL", "")
FULL_REPORT_BUTTON_TEXT = os.environ.get(
    "FULL_REPORT_BUTTON_TEXT", "💎 Получить мой полный профиль"
)

# --------------------------------------------------------------------------
# ПСИХОТИПЫ DISC (цветовая модель Марстона)
#   R = Красный  = Dominance      (доминирование)
#   Y = Жёлтый   = Influence      (влияние)
#   G = Зелёный  = Steadiness     (постоянство)
#   B = Синий    = Conscientious  (добросовестность)
# --------------------------------------------------------------------------

PROFILES = {
    "R": {
        "name": "Красный",
        "subtitle": "Доминирование — нацелен на результат",
        "emoji": "🔴",
        "strengths": [
            "быстро принимает решения и берёт ответственность на себя",
            "не боится закрывать сделку и предлагать купить",
            "настойчив и не сдаётся после первого отказа",
            "конкурентен, любит вызовы и высокие цели",
        ],
        "weaknesses": [
            "может давить на клиента и торопить с решением",
            "нетерпелив, не любит рутину и отчётность",
            "порой не дослушивает клиента до конца",
            "может показаться резким или излишне напористым",
        ],
        "recommendations": [
            "тренируйте паузы: после предложения — молчите и слушайте клиента",
            "задавайте на 2-3 уточняющих вопроса больше, чем хочется",
            "фиксируйте договорённости письменно, не полагайтесь на память",
            "перед звонком напоминайте себе: «сначала понять, потом продать»",
        ],
    },
    "Y": {
        "name": "Жёлтый",
        "subtitle": "Влияние — заряжает энтузиазмом и общением",
        "emoji": "🟡",
        "strengths": [
            "легко устанавливает контакт и располагает к себе",
            "создаёт позитивную, живую атмосферу в разговоре",
            "ярко и увлекательно презентует продукт",
            "заражает энтузиазмом и вдохновляет на покупку",
        ],
        "weaknesses": [
            "может забывать детали и договорённости",
            "иногда обещает больше, чем способен выполнить",
            "теряется, когда нужно оперировать точными цифрами",
            "откладывает рутину — CRM, отчёты, последующие звонки",
        ],
        "recommendations": [
            "используйте чек-лист и CRM для каждой сделки — не полагайтесь на память",
            "готовьте заранее 2-3 конкретных цифры и факта под возражения",
            "фиксируйте все договорённости в переписке сразу после звонка",
            "тренируйте прямое предложение закрыть сделку, а не только «атмосферу»",
        ],
    },
    "G": {
        "name": "Зелёный",
        "subtitle": "Постоянство — строит доверие и долгие отношения",
        "emoji": "🟢",
        "strengths": [
            "терпелив, надёжен, вызывает доверие клиента",
            "отлично выстраивает долгосрочные отношения",
            "внимательно слушает и правда слышит клиента",
            "стабилен под давлением, не паникует в сложных ситуациях",
        ],
        "weaknesses": [
            "избегает давления и боится показаться навязчивым",
            "медленно и осторожно подводит клиента к закрытию сделки",
            "тяжело переживает отказы, может «застревать» в сомнениях",
            "неохотно поднимает неудобные темы (цена, сроки, сравнение с конкурентами)",
        ],
        "recommendations": [
            "ставьте себе чёткий дедлайн по каждой сделке — когда именно предложить закрыть",
            "тренируйте фразу-переход: «Если всё устраивает — оформляем?»",
            "напоминайте себе, что прямой вопрос — это забота о клиенте, а не давление",
            "разбирайте отказы как статистику, а не как личную неудачу",
        ],
    },
    "B": {
        "name": "Синий",
        "subtitle": "Добросовестность — точность, факты, экспертность",
        "emoji": "🔵",
        "strengths": [
            "тщательно готовится и глубоко знает продукт",
            "даёт точные, аргументированные ответы на возражения",
            "вызывает доверие как эксперт, не даёт пустых обещаний",
            "системно ведёт клиента и не упускает детали",
        ],
        "weaknesses": [
            "может «тонуть» в деталях и затягивать с предложением",
            "медленно принимает решения там, где нужна скорость",
            "избегает эмоционального контакта, может казаться холодным",
            "трудно импровизирует, если разговор уходит от плана",
        ],
        "recommendations": [
            "тренируйте small talk — 1-2 минуты живого общения перед делом",
            "устанавливайте себе лимит времени на подготовку и анализ",
            "упрощайте презентацию: 3 ключевых аргумента вместо десяти",
            "чаще проговаривайте не только факты, но и выгоду для клиента",
        ],
    },
}

# --------------------------------------------------------------------------
# 20 ВОПРОСОВ ТЕСТА
# Каждый вопрос — 4 варианта ответа, каждый вариант соответствует одному
# из психотипов (R/Y/G/B). Порядок вариантов внутри вопроса перемешан,
# чтобы один и тот же психотип не был всегда "первым в списке".
# --------------------------------------------------------------------------

QUESTIONS = [
    {
        "text": "Когда я звоню новому клиенту впервые, я...",
        "options": [
            ("Сразу создаю лёгкую атмосферу, шучу", "Y"),
            ("Сразу перехожу к делу и выгоде", "R"),
            ("Заранее готовлю факты о клиенте", "B"),
            ("Говорю спокойно, даю освоиться", "G"),
        ],
    },
    {
        "text": "В переговорах о цене я обычно...",
        "options": [
            ("Уверенно называю цену и её ценность", "R"),
            ("Подстраиваюсь под бюджет клиента", "G"),
            ("Привожу расчёты и сравнения", "B"),
            ("Делаю акцент на эмоциях, не цифрах", "Y"),
        ],
    },
    {
        "text": "Если клиент долго не отвечает, я...",
        "options": [
            ("Звоню сам и прямо спрашиваю решение", "R"),
            ("Пишу дружелюбное сообщение-напоминание", "Y"),
            ("Жду — не хочу быть навязчивым", "G"),
            ("Анализирую, на каком этапе застряли", "B"),
        ],
    },
    {
        "text": "Коллеги говорят, что я в продажах...",
        "options": [
            ("Душа компании, заряжаю людей", "Y"),
            ("Напористый, нацелен на результат", "R"),
            ("Очень подготовленный, знаю детали", "B"),
            ("Надёжный, довожу дело до конца", "G"),
        ],
    },
    {
        "text": "Когда клиент говорит «дорого», я...",
        "options": [
            ("Привожу расчёт окупаемости, цифры", "B"),
            ("Сразу предлагаю альтернативу", "R"),
            ("Рассказываю истории других клиентов", "Y"),
            ("Спокойно выясняю, что за этим стоит", "G"),
        ],
    },
    {
        "text": "Моя главная сила в продажах — это...",
        "options": [
            ("Терпение и умение вызвать доверие", "G"),
            ("Экспертность и точность", "B"),
            ("Скорость и решительность", "R"),
            ("Обаяние, умею расположить к себе", "Y"),
        ],
    },
    {
        "text": "Моя главная слабость в продажах — это...",
        "options": [
            ("Иногда давлю и тороплю с решением", "R"),
            ("Забываю детали и договорённости", "Y"),
            ("Боюсь быть навязчивым, тяну время", "G"),
            ("Слишком долго готовлюсь перед шагом", "B"),
        ],
    },
    {
        "text": "На встрече с клиентом мне больше всего нравится...",
        "options": [
            ("Живое общение и импровизация", "Y"),
            ("Показывать конкретные цифры и кейсы", "B"),
            ("Сразу переходить к сути и решению", "R"),
            ("Слушать, что действительно важно клиенту", "G"),
        ],
    },
    {
        "text": "Когда сделка срывается, я...",
        "options": [
            ("Долго переживаю и анализирую причины", "G"),
            ("Быстро иду к следующему клиенту", "R"),
            ("Разбираю ошибку по пунктам", "B"),
            ("Расстраиваюсь, но быстро нахожу позитив", "Y"),
        ],
    },
    {
        "text": "В работе с CRM и отчётами я...",
        "options": [
            ("Веду всё аккуратно и подробно", "B"),
            ("Заполняю по минимуму — главное результат", "R"),
            ("Часто забываю или откладываю", "Y"),
            ("Веду стабильно, но без энтузиазма", "G"),
        ],
    },
    {
        "text": "Если клиент груб или раздражён, я...",
        "options": [
            ("Отвечаю уверенно, не теряюсь", "R"),
            ("Стараюсь сгладить и успокоить", "G"),
            ("Перевожу разговор в лёгкое русло", "Y"),
            ("Спокойно и по фактам разбираю суть", "B"),
        ],
    },
    {
        "text": "Что мотивирует меня больше всего в продажах?",
        "options": [
            ("Рейтинги, победа, высокий доход", "R"),
            ("Признание и живое общение с людьми", "Y"),
            ("Стабильность и доверие клиентов", "G"),
            ("Профессионализм и экспертный статус", "B"),
        ],
    },
    {
        "text": "Готовясь к сложным переговорам, я...",
        "options": [
            ("Тщательно изучаю всю информацию", "B"),
            ("Продумываю главный аргумент и иду", "R"),
            ("Настраиваюсь эмоционально", "G"),
            ("Думаю, как расположить собеседника", "Y"),
        ],
    },
    {
        "text": "Когда нужно закрыть сделку «здесь и сейчас», я...",
        "options": [
            ("Прямо предлагаю оформить и объясняю почему сейчас", "R"),
            ("Создаю ощущение выгоды и позитива", "Y"),
            ("Подытоживаю аргументы логически", "B"),
            ("Аккуратно спрашиваю без давления", "G"),
        ],
    },
    {
        "text": "В команде я обычно играю роль...",
        "options": [
            ("Вдохновителя, поднимаю настроение", "Y"),
            ("Лидера, толкаю всех к результату", "R"),
            ("Человека, на которого можно положиться", "G"),
            ("Эксперта, к которому идут за советом", "B"),
        ],
    },
    {
        "text": "Больше всего меня раздражает в продажах...",
        "options": [
            ("Хаос и отсутствие данных", "B"),
            ("Медлительность и нерешительность", "R"),
            ("Давление, конфликты, агрессия", "G"),
            ("Скучная рутина и монотонность", "Y"),
        ],
    },
    {
        "text": "Принимая решение по сложному клиенту, я опираюсь на...",
        "options": [
            ("Факты, цифры и логику", "B"),
            ("Интуицию и желание действовать быстро", "R"),
            ("Ощущение доверия с клиентом", "G"),
            ("Общую атмосферу и реакцию клиента", "Y"),
        ],
    },
    {
        "text": "Если план продаж под угрозой, я...",
        "options": [
            ("Усиливаю напор, ищу быстрые решения", "R"),
            ("Подключаю нетворкинг и контакты", "Y"),
            ("Анализирую воронку, ищу узкое место", "B"),
            ("Спокойно и системно дожимаю текущих", "G"),
        ],
    },
    {
        "text": "Обратную связь от руководителя легче воспринимаю, если она...",
        "options": [
            ("Структурирована, с конкретными фактами", "B"),
            ("Короткая и по делу, без «воды»", "R"),
            ("Подана мягко и доброжелательно", "G"),
            ("С признанием моих усилий, позитивная", "Y"),
        ],
    },
    {
        "text": "Через месяц работы клиент вспомнит меня как...",
        "options": [
            ("Приятного и энергичного человека", "Y"),
            ("Уверенного профессионала с результатом", "R"),
            ("Эксперта, разложившего всё по полочкам", "B"),
            ("Надёжного человека, с которым комфортно", "G"),
        ],
    },
]

TOTAL_QUESTIONS = len(QUESTIONS)

# --------------------------------------------------------------------------
# МОТИВАТОРЫ (модель Спрэнгера / PIAV: Theoretical, Utilitarian, Aesthetic,
# Social, Individualistic, Traditional)
#
# Это ОТДЕЛЬНАЯ методика от DISC (не часть её) — DISC описывает КАК человек
# ведёт себя, мотиваторы — ПОЧЕМУ он это делает / что его реально включает.
#
# Формат: каждый вопрос — одно утверждение, пользователь оценивает степень
# согласия по шкале 1-5 (а не выбирает из 4 вариантов, как в DISC). Балл по
# категории — сумма ответов по её 4 вопросам (диапазон 4-20).
# --------------------------------------------------------------------------

MOTIVATOR_PROFILES = {
    "T": {
        "name": "Развития",
        "emoji": "🧠",
        "subtitle": "Мне важно становиться сильнее и знать больше",
        "teaser": (
            "Тебя двигает вперёд любопытство и желание разобраться в сути — "
            "не поверхностно, а по-настоящему."
        ),
    },
    "U": {
        "name": "Результата",
        "emoji": "💰",
        "subtitle": "Мне важно видеть деньги и конкретную отдачу",
        "teaser": (
            "Тебе важно видеть конкретную отдачу от своих усилий. Просто "
            "«интересная работа» тебя надолго не удержит — тебе нужно "
            "понимать: что я получу, какой будет результат."
        ),
    },
    "A": {
        "name": "Гармонии",
        "emoji": "✨",
        "subtitle": "Мне важно, чтобы работа приносила удовольствие, красоту и баланс",
        "teaser": (
            "Тебе важно не только ЧТО сделано, но и КАК — форма, атмосфера "
            "и гармония процесса имеют для тебя реальное значение."
        ),
    },
    "S": {
        "name": "Пользы",
        "emoji": "❤️",
        "subtitle": "Мне важно помогать людям и видеть смысл в том, что я делаю",
        "teaser": (
            "Тебя мотивирует ощущение, что твоя работа реально помогает "
            "людям, а не только приносит прибыль."
        ),
    },
    "I": {
        "name": "Свободы",
        "emoji": "👑",
        "subtitle": "Мне важно самому принимать решения, иметь влияние и чувствовать свою силу",
        "teaser": (
            "Тебе важно не просто заработать — тебе важно самому решать, "
            "как, с кем и куда двигаться. Жёсткий контроль и работа «по "
            "указке» быстро снижают твою мотивацию."
        ),
    },
    "TR": {
        "name": "Принципов",
        "emoji": "⚖️",
        "subtitle": "Мне важно работать по своим ценностям, правилам и системе",
        "teaser": (
            "Тебе комфортнее и эффективнее работается, когда есть чёткая "
            "система и понятные принципы, а не хаос и импровизация."
        ),
    },
}

MOTIVATOR_QUESTIONS = [
    {
        "text": "Мне важно разбираться в теме до конца, прежде чем принять решение, даже если это займёт больше времени.",
        "category": "T",
    },
    {
        "text": "Для меня важнее конкретный измеримый результат, чем сам процесс работы.",
        "category": "U",
    },
    {
        "text": "Мне важно, чтобы то, что я делаю, было не только эффективным, но и красиво/аккуратно оформлено.",
        "category": "A",
    },
    {
        "text": "Для меня важно, чтобы моя работа реально помогала людям, а не только приносила прибыль.",
        "category": "S",
    },
    {
        "text": "Мне важно быть заметной(ым), быть тем, кто задаёт тон и ведёт за собой.",
        "category": "I",
    },
    {
        "text": "Мне важно, чтобы у работы были чёткие правила, принципы и структура.",
        "category": "TR",
    },
    {
        "text": "Я получаю удовольствие от изучения нового — курсы, книги, статьи — даже если это напрямую не нужно для работы прямо сейчас.",
        "category": "T",
    },
    {
        "text": "Я быстро теряю интерес к задаче, если не вижу, как она влияет на деньги или эффективность.",
        "category": "U",
    },
    {
        "text": "Я обращаю внимание на атмосферу и стиль общения не меньше, чем на суть разговора.",
        "category": "A",
    },
    {
        "text": "Я получаю искреннее удовлетворение, когда вижу, что клиенту стало лучше благодаря мне.",
        "category": "S",
    },
    {
        "text": "Признание моих достижений мотивирует меня сильнее, чем сама задача.",
        "category": "I",
    },
    {
        "text": "Я ценю проверенные методы и системы больше, чем эксперименты «на удачу».",
        "category": "TR",
    },
    {
        "text": "В разговоре меня больше цепляет обсуждение идей и закономерностей, чем конкретные бытовые детали.",
        "category": "T",
    },
    {
        "text": "Оценивая новую идею, я сразу задаюсь вопросом: «А какая от этого практическая польза?»",
        "category": "U",
    },
    {
        "text": "Меня раздражает хаос и неаккуратность в работе, даже если результат в итоге получен.",
        "category": "A",
    },
    {
        "text": "Мне сложно продавать то, в пользе чего для человека я не уверена.",
        "category": "S",
    },
    {
        "text": "Я люблю ситуации, где могу проявить лидерство и повлиять на решение.",
        "category": "I",
    },
    {
        "text": "Мне некомфортно, когда решения принимаются без опоры на устоявшиеся принципы или регламент.",
        "category": "TR",
    },
    {
        "text": "Я скорее задам вопрос «почему это работает именно так», чем просто приму правило как есть.",
        "category": "T",
    },
    {
        "text": "Меня больше вдохновляет рост показателей (продажи, прибыль, KPI), чем абстрактное развитие.",
        "category": "U",
    },
    {
        "text": "Мне важно, чтобы процесс работы был гармоничным, а не только результативным.",
        "category": "A",
    },
    {
        "text": "Забота о команде и коллегах для меня так же важна, как личные результаты.",
        "category": "S",
    },
    {
        "text": "Быть первой или лучшей в чём-то — важная часть моей мотивации.",
        "category": "I",
    },
    {
        "text": "Я скорее буду следовать выработанной системе, чем изобретать что-то новое каждый раз.",
        "category": "TR",
    },
]

TOTAL_MOTIVATOR_QUESTIONS = len(MOTIVATOR_QUESTIONS)

# --------------------------------------------------------------------------
# ЛОГИКА БОТА
# --------------------------------------------------------------------------


def build_question_keyboard(qindex: int, options) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"ans|{qindex}|{ptype}")]
        for label, ptype in options
    ]
    return InlineKeyboardMarkup(buttons)


async def send_question(update_or_query, context: ContextTypes.DEFAULT_TYPE, qindex: int):
    question = QUESTIONS[qindex]
    text = f"Вопрос {qindex + 1} из {TOTAL_QUESTIONS}\n\n{question['text']}"
    keyboard = build_question_keyboard(qindex, question["options"])

    if hasattr(update_or_query, "message") and update_or_query.message is not None:
        # Первый вопрос — обычное сообщение
        await update_or_query.message.reply_text(text, reply_markup=keyboard)
    else:
        # Callback-запрос — редактируем предыдущее сообщение
        await update_or_query.edit_message_text(text, reply_markup=keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если пользователь уже начинал тест, но не дошёл до конца (current_q
    # задан и не None) — это значит, что предыдущий прогон прервался
    # (например, бот перезапускался и его прогресс не сохранился).
    # Явно предупреждаем об этом, а не тихо перезаписываем данные.
    unfinished = context.user_data.get("current_q") is not None
    already_has_result = context.user_data.get("disc_scores") is not None

    context.user_data["scores"] = {"R": 0, "Y": 0, "G": 0, "B": 0}
    context.user_data["current_q"] = 0

    if unfinished:
        await update.message.reply_text(
            "⚠️ Похоже, твой предыдущий тест не был завершён и его результаты "
            "не сохранились. Начинаем заново — отвечай на все вопросы, "
            "чтобы получить результат."
        )
    elif already_has_result:
        await update.message.reply_text(
            "Ты уже проходила этот тест раньше. Если хочешь пройти заново — "
            "предыдущий результат будет заменён новым."
        )

    intro = (
        "Привет! 👋\n\n"
        "Это короткий тест на твой психотип продавца по методу DISC "
        "(Красный / Жёлтый / Зелёный / Синий).\n\n"
        f"Тебя ждёт {TOTAL_QUESTIONS} вопросов, отвечай честно и быстро — "
        "первый вариант, который откликается, обычно самый точный.\n"
        "В конце ты узнаешь свои 2 ведущих психотипа.\n\n"
        "Погнали!"
    )
    await update.message.reply_text(intro)
    await send_question(update, context, 0)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команда /start — начать (или начать заново) тест на психотип продавца."
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, qindex_str, ptype = query.data.split("|")
        qindex = int(qindex_str)
    except (ValueError, AttributeError):
        return

    current_q = context.user_data.get("current_q")
    scores = context.user_data.get("scores")

    if current_q is None or scores is None:
        await query.edit_message_text(
            "⚠️ Результаты предыдущего теста не сохранились (бот перезапускался). "
            "Нажми /start, чтобы пройти заново."
        )
        return

    if qindex != current_q:
        # Пользователь нажал на кнопку из уже отвеченного вопроса
        return

    scores[ptype] = scores.get(ptype, 0) + 1
    next_q = current_q + 1
    context.user_data["current_q"] = next_q

    if next_q < TOTAL_QUESTIONS:
        await send_question(query, context, next_q)
    else:
        await show_result(query, context, scores)


# --------------------------------------------------------------------------
# ЛОГИКА ТЕСТА НА МОТИВАТОРЫ (запускается кнопкой после результата DISC)
# --------------------------------------------------------------------------


def build_motivator_keyboard(qindex: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(value), callback_data=f"manswer|{qindex}|{value}")
        for value in range(1, 6)
    ]
    return InlineKeyboardMarkup([buttons])


async def send_motivator_question(query, context: ContextTypes.DEFAULT_TYPE, qindex: int):
    question = MOTIVATOR_QUESTIONS[qindex]
    text = (
        f"Вопрос {qindex + 1} из {TOTAL_MOTIVATOR_QUESTIONS}\n\n"
        f"{question['text']}\n\n"
        "1 — совсем не про меня   ...   5 — точно про меня"
    )
    keyboard = build_motivator_keyboard(qindex)
    await query.edit_message_text(text, reply_markup=keyboard)


async def start_motivators(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["m_scores"] = {code: 0 for code in MOTIVATOR_PROFILES}
    context.user_data["m_current_q"] = 0

    intro = (
        "🧭 Второй тест: что тебя реально мотивирует и двигает.\n\n"
        f"Тебя ждёт {TOTAL_MOTIVATOR_QUESTIONS} коротких утверждений. "
        "Оцени каждое по шкале от 1 до 5 — насколько это похоже на тебя.\n\n"
        "Отвечай быстро, первое ощущение обычно самое точное."
    )
    await query.edit_message_text(intro)
    await query.message.reply_text(
        f"Вопрос 1 из {TOTAL_MOTIVATOR_QUESTIONS}\n\n"
        f"{MOTIVATOR_QUESTIONS[0]['text']}\n\n"
        "1 — совсем не про меня   ...   5 — точно про меня",
        reply_markup=build_motivator_keyboard(0),
    )


async def handle_motivator_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, qindex_str, value_str = query.data.split("|")
        qindex = int(qindex_str)
        value = int(value_str)
    except (ValueError, AttributeError):
        return

    current_q = context.user_data.get("m_current_q")
    scores = context.user_data.get("m_scores")

    if current_q is None or scores is None:
        await query.edit_message_text(
            "⚠️ Результаты предыдущего теста не сохранились (бот перезапускался). "
            "Нажми /start, пройди DISC-тест заново, а потом снова запусти тест на мотиваторы."
        )
        return

    if qindex != current_q:
        return

    category = MOTIVATOR_QUESTIONS[qindex]["category"]
    scores[category] = scores.get(category, 0) + value
    next_q = current_q + 1
    context.user_data["m_current_q"] = next_q

    if next_q < TOTAL_MOTIVATOR_QUESTIONS:
        await send_motivator_question(query, context, next_q)
    else:
        await show_motivator_result(query, context, scores)


def format_motivator_result_text(scores: dict) -> str:
    """Бесплатный результат по коду мотивации — та же логика урезанности, что в DISC.

    Показывает только топ-1 код словами, без баллов по остальным 5
    категориям. Полная раскладка остаётся для платного синтеза.
    """
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top1_code, _ = ranked[0]
    top1 = MOTIVATOR_PROFILES[top1_code]

    lines = []
    lines.append(f"💰 <b>Твой код мотивации в деньгах — {top1['name'].upper()}</b>\n")
    lines.append(top1["teaser"])
    lines.append("")
    lines.append(
        "Помни: нет «правильных» и «неправильных» кодов — есть то, что "
        "реально включает тебя, и то, что стоит осознанно использовать."
    )

    return "\n".join(lines)


def format_motivator_full_text(scores: dict) -> str:
    """Полный (платный) результат по кодам мотивации — все 6 категорий с баллами.

    Пока нигде не вызывается. Понадобится для объединённого платного отчёта
    вместе с полным результатом DISC (format_full_result_text).
    """
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    lines = []
    lines.append("💰 <b>Твой полный профиль кодов мотивации</b>\n")
    for code, score in ranked:
        p = MOTIVATOR_PROFILES[code]
        lines.append(f"{p['emoji']} Код {p['name']}: {score}/20")
    lines.append("")

    top1_code, _ = ranked[0]
    top1 = MOTIVATOR_PROFILES[top1_code]
    lines.append(f"<b>Ведущий код: {top1['emoji']} {top1['name']}</b>")
    lines.append(f"{top1['subtitle']}.")
    lines.append(top1["teaser"])

    return "\n".join(lines)


def build_synthesis_text(disc_scores: dict, motivator_scores: dict) -> str:
    """«Соединяем DISC + код» — мостик между двумя тестами до платного оффера.

    Собирается динамически из реальных данных пользователя (доминирующий
    DISC-тип + доминирующий код), а не из 24 захардкоженных комбинаций —
    так получается персонально, но без ручного написания текста на каждую
    из 4×6 пар. Полноценный AI-синтез (через Claude API) — следующий шаг,
    когда будет готова платная часть с реальной генерацией.
    """
    disc_ranked = sorted(disc_scores.items(), key=lambda item: item[1], reverse=True)
    disc_top1 = PROFILES[disc_ranked[0][0]]

    m_ranked = sorted(motivator_scores.items(), key=lambda item: item[1], reverse=True)
    m_top1 = MOTIVATOR_PROFILES[m_ranked[0][0]]

    lines = [
        "🔥 <b>Теперь становится интереснее.</b>\n",
        f"Твой DISC показывает: {disc_top1['strengths'][0]}.",
        f"Твой код мотивации показывает: {m_top1['teaser']}",
        "",
        (
            f"А вместе это даёт особую комбинацию. Ты можешь быть очень "
            f"сильным продавцом — но именно здесь может быть твоё слепое "
            f"пятно: {disc_top1['weaknesses'][0]}, и твоё стремление к "
            f"«{m_top1['name'].lower()}» может это только усиливать."
        ),
        "",
        (
            "Вот почему одного DISC недостаточно — важно понимать не "
            "только как ты продаёшь, но и что стоит за твоим поведением."
        ),
    ]
    return "\n".join(lines)


def format_paid_offer_text() -> str:
    """Финальный платный оффер — показывается после блока 'соединения'.

    Содержит структуру из 15 пунктов, которую Айгерим утвердила как
    финальный отчёт, и явную цену/CTA. Пока без автоматической оплаты —
    ADMIN_CONTACT_URL/кнопка ведут на ручное оформление.
    """
    lines = [
        "🔐 <b>Хочешь увидеть полную картину?</b>\n",
        (
            "Сейчас ты знаешь только две части своего профиля: DISC — как "
            "ты проявляешь себя в продажах, и код мотивации — что тебя "
            "внутренне двигает. Но самое ценное начинается там, где эти "
            "два показателя соединяются."
        ),
        "",
        "В полном персональном разборе ты узнаешь:",
        "1. Мой DISC",
        "2. Мой код мотивации",
        "3. Как я принимаю решения",
        "4. Как я продаю",
        "5. Как я проявляюсь с клиентом",
        "6. Мои сильные стороны",
        "7. Мои риски",
        "8. Моё главное слепое пятно",
        "9. Мои денежные драйверы",
        "10. Что меня демотивирует",
        "11. Какие клиенты мне подходят",
        "12. С какими клиентами сложнее",
        "13. Как мне адаптировать продажи",
        "14. Как мне вести переговоры",
        "15. Мой персональный план развития",
        "",
        "💎 Это не два теста — это твоя персональная карта продавца.",
        "",
        f"💳 Стоимость полного разбора — {FULL_REPORT_PRICE}",
    ]
    return "\n".join(lines)


async def show_motivator_result(query, context: ContextTypes.DEFAULT_TYPE, scores: dict):
    result_text = format_motivator_result_text(scores)

    disc_scores = context.user_data.get("disc_scores")

    await query.edit_message_text(result_text, parse_mode=ParseMode.HTML, reply_markup=None)

    # Блок "соединения" — только если есть оба результата (обычный порядок
    # прохождения). Если DISC-баллы почему-то отсутствуют (например,
    # прогресс потерялся при перезапуске бота), пропускаем синтез и сразу
    # предлагаем полный оффер — так пользователь не застревает без ответа.
    if disc_scores is not None:
        synthesis_text = build_synthesis_text(disc_scores, scores)
        await query.message.reply_text(synthesis_text, parse_mode=ParseMode.HTML)

    offer_text = format_paid_offer_text()

    if ADMIN_CONTACT_URL:
        offer_buttons = InlineKeyboardMarkup(
            [[InlineKeyboardButton(FULL_REPORT_BUTTON_TEXT, url=ADMIN_CONTACT_URL)]]
        )
        await query.message.reply_text(
            offer_text, parse_mode=ParseMode.HTML, reply_markup=offer_buttons
        )
    else:
        await query.message.reply_text(
            offer_text + "\n\n👉 Напиши мне в личные сообщения, чтобы получить полный разбор.",
            parse_mode=ParseMode.HTML,
        )

    # Баллы мотиваторов сохраняем — понадобятся для полного платного отчёта
    # вместе с disc_scores (см. format_full_result_text / format_motivator_full_text).
    context.user_data["motivator_scores"] = scores
    context.user_data["m_current_q"] = None
    context.user_data["m_scores"] = None


def format_result_text(scores: dict) -> str:
    """Бесплатный результат — законченный мини-разбор, но осознанно неполный.

    Структура (по примеру, который утвердила Айгерим):
      - профиль (2 ведущих психотипа + краткое связное описание)
      - 1 зона риска (не полный список, только самая характерная)
      - 1 главный совет (не полный список рекомендаций)
      - явная рамка "это только 20% профиля"

    Полный список "зон роста" и "рекомендаций" остаётся в PROFILES и
    используется в format_full_result_text() — платной версии.
    """
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top1_code, _ = ranked[0]
    top2_code, _ = ranked[1]

    top1 = PROFILES[top1_code]
    top2 = PROFILES[top2_code]

    lines = []
    lines.append("🎯 <b>Твой результат готов!</b>\n")
    lines.append(
        f"<b>Твой профиль: {top1['emoji']} {top1['name']} "
        f"+ {top2['emoji']} {top2['name']}</b>\n"
    )

    # Краткое связное описание из "сильных сторон" обоих типов
    summary = " ".join(
        s.capitalize() + "."
        for profile in (top1, top2)
        for s in profile["strengths"][:1]
    )
    lines.append(summary)
    lines.append("")

    # 1 зона риска — берём первую (самую характерную) у ведущего типа
    lines.append(f"<b>Твоя зона риска:</b> {top1['weaknesses'][0]}.")
    lines.append("")

    # 1 главный совет — берём первую рекомендацию у ведущего типа
    lines.append(f"<b>Главный совет:</b> {top1['recommendations'][0]}.")
    lines.append("")

    lines.append(
        "Помни: нет «плохих» и «хороших» психотипов — есть особенности, "
        "которые можно использовать в свою пользу, если знать, как именно."
    )
    lines.append("")
    lines.append("📊 Это только 20% твоего профиля.")

    return "\n".join(lines)


def format_bridge_to_motivators_text() -> str:
    """Короткое сообщение-мостик после DISC — приглашение ко второму тесту.

    Раньше здесь был длинный список вопросов + пример слепого пятна —
    теперь этот контент переехал в format_paid_offer_text(), потому что
    появился отдельный шаг "соединения" между двумя тестами (см.
    build_synthesis_text) и он сам по себе достаточно сильный крючок.
    """
    lines = [
        "Ты узнал(а), <b>КАК</b> ты ведёшь себя в продажах.",
        "",
        "Но пока мы не знаем:",
        "💰 что именно заставляет тебя действовать и зарабатывать;",
        "🔥 что тебя включает и заряжает;",
        "🚫 что тебя демотивирует.",
        "",
        "Чтобы это узнать, пройди второй мини-тест — «Твой код мотивации в деньгах».",
    ]
    return "\n".join(lines)


def format_full_result_text(scores: dict) -> str:
    """Полный (платный) результат по DISC — зоны роста + рекомендации.

    Пока нигде не вызывается в текущем сценарии /start. Оставлена для
    следующего этапа: объединение с результатами теста на мотиваторы
    в единый отчёт, открываемый после оплаты или команды /unlock.
    """
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top1_code, top1_score = ranked[0]
    top2_code, top2_score = ranked[1]

    top1 = PROFILES[top1_code]
    top2 = PROFILES[top2_code]

    lines = []
    lines.append("🎯 <b>Твой полный разбор</b>\n")
    lines.append("Баллы по психотипам:")
    for code, score in ranked:
        p = PROFILES[code]
        lines.append(f"{p['emoji']} {p['name']}: {score}/{TOTAL_QUESTIONS}")
    lines.append("")

    lines.append(
        f"<b>Твои 2 ведущих психотипа: {top1['emoji']} {top1['name']} "
        f"+ {top2['emoji']} {top2['name']}</b>\n"
    )

    for profile in (top1, top2):
        lines.append(f"{profile['emoji']} <b>{profile['name']} — {profile['subtitle']}</b>")
        lines.append("<u>Сильные стороны:</u>")
        for s in profile["strengths"]:
            lines.append(f"✅ {s}")
        lines.append("<u>Зоны роста:</u>")
        for w in profile["weaknesses"]:
            lines.append(f"⚠️ {w}")
        lines.append("<u>Рекомендации:</u>")
        for r in profile["recommendations"]:
            lines.append(f"💡 {r}")
        lines.append("")

    lines.append(
        "Помни: нет «плохих» и «хороших» психотипов — есть сильные стороны, "
        "которые стоит использовать, и зоны роста, которые стоит развивать."
    )

    return "\n".join(lines)


async def show_result(query, context: ContextTypes.DEFAULT_TYPE, scores: dict):
    result_text = format_result_text(scores)
    bridge_text = format_bridge_to_motivators_text()

    cta_buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Узнать свой код мотивации", callback_data="start_motivators")],
            [InlineKeyboardButton(CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)],
            [InlineKeyboardButton(COURSE_BUTTON_TEXT, url=COURSE_URL)],
        ]
    )

    # Результат и мостик — раздельными сообщениями, чтобы бесплатный разбор
    # не сливался визуально с приглашением на второй тест.
    await query.edit_message_text(
        result_text, parse_mode=ParseMode.HTML, reply_markup=None
    )
    await query.message.reply_text(bridge_text, parse_mode=ParseMode.HTML)
    await query.message.reply_text(
        "Что дальше? 👇", reply_markup=cta_buttons
    )

    # Баллы DISC сохраняем (не обнуляем!) — понадобятся позже для полного
    # платного отчёта, который объединит их с результатами теста на мотиваторы.
    context.user_data["disc_scores"] = scores
    context.user_data["current_q"] = None
    context.user_data["scores"] = None


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Ошибка при обработке апдейта: %s", update, exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан. Установи переменную окружения BOT_TOKEN "
            "(токен из @BotFather) перед запуском."
        )

    persistence = PicklePersistence(filepath=PERSISTENCE_PATH)
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern=r"^ans\|"))
    application.add_handler(CallbackQueryHandler(start_motivators, pattern=r"^start_motivators$"))
    application.add_handler(CallbackQueryHandler(handle_motivator_answer, pattern=r"^manswer\|"))
    application.add_error_handler(on_error)

    logger.info("Бот запущен, ждём сообщения...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
