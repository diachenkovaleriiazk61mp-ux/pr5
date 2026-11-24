import argparse
import csv
import json
from pathlib import Path
from statistics import median


def fmt(value):
    if value is None:
        return '—'
    if isinstance(value, str):
        return value
    return f'{value:.6g}'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                       '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                      ['| ' + ' | '.join(fmt(x) for x in row) + ' |' for row in rows])


def build(directory):
    directory = Path(directory)
    machine = json.loads((directory / 'machine.json').read_text(encoding='utf-8'))
    med = {}
    full = []
    for mode in ('global', 'rw'):
        for kind in ('serial', 'parallel'):
            runs = [json.loads(p.read_text(encoding='utf-8'))
                    for p in sorted(directory.glob(f'{kind}-{mode}-*.json'))]
            if len(runs) != machine['repeats']:
                raise RuntimeError(f'Incomplete results: {kind}, {mode}')
            assert all(r['invariants'] for r in runs)
            full.extend(runs)
            med[mode, kind] = dict(
                X=median(r['X'] for r in runs),
                roles={role: {key: median(r['roles'][role][key] for r in runs)
                              for key in runs[0]['roles'][role]}
                       for role in ('write', 'read')},
                threads=[median(r['threads'][i]['counts']['write' if i % 2 == 0 else 'read'] for r in runs)
                         for i in range(9)] if kind == 'parallel' else [])
    g, rw = med['global', 'parallel'], med['rw', 'parallel']
    serial_g, serial_rw = med['global', 'serial'], med['rw', 'serial']
    csw, csr = (serial_g['roles'][r]['t_cs_us'] for r in ('write', 'read'))
    cs = (5 * csw + 4 * csr) / 9 / 1e6
    limit = 1 / cs
    metrics = {
        'S_global': g['X'] / serial_g['X'],
        'E_global': g['X'] / serial_g['X'] / 9,
        'S_rw': rw['X'] / serial_rw['X'],
        'E_rw': rw['X'] / serial_rw['X'] / 9,
        'S_w': rw['roles']['write']['X'] / g['roles']['write']['X'],
        'S_r': rw['roles']['read']['X'] / g['roles']['read']['X'],
        'S_total': rw['X'] / g['X'], 'rho': g['X'] * cs}
    text = [
        '# Лабораторна робота №5',
        '**Проєктування потокобезпечної структури даних**',
        'Дьяченко Валерія, ЗК-61мп. Варіант 7.',
        '## Мета',
        'Реалізувати впорядкований однозв’язний список і порівняти доступ до нього з глобальним замком та RWLock.',
        '## 1. Структура та стенд',
        'Реалізовано власні вузли зі значенням key і посиланням next. '
        'Методи add та remove змінюють список і лічильник розміру; contains лише обходить вузли. '
        'Ключі від 0 до 1023. Початково записано 512 парних ключів. '
        'Непарні потоки виконують add і remove почергово; парні виконують contains. '
        'Ключі рівномірно генеруються локальним генератором кожного потоку до виклику операції.',
        'Кожен прогін має спільне для всіх потоків вікно: прогрів 1 с, замір 10 с. '
        'Запуск потоків узгоджується бар’єром. Для X враховано операції, '
        'виклик і повернення яких потрапили у вікно заміру. Перехідні операції '
        'пораховано окремо в boundary. Очікування на межах вікна обрізано за його межами, '
        'тому w описує саме час очікування в межах D. Максимум очікування також обчислено '
        'для всіх перетинів з вікном, зокрема операцій, що завершилися після нього.',
        'Тривалість охоплює захоплення замка, роботу зі списком і звільнення замка. '
        'Зберігається кожна тривалість і кожен час очікування без вибірки. '
        'Перцентилі обчислено методом найближчого рангу. Під час заміру немає друку або запису на диск.',
        'Табличні показники — медіани трьох прогонів кожного режиму. '
        'Похідні метрики таблиці 5 обчислено з цих медіан. '
        'Оскільки медіани взято окремо, сума медіан ролей може трохи відрізнятися від медіани загальної швидкості.',
        '### Таблиця 1. Стенд',
        table(['n', 'n_w', 'n_r', 'Мова і версія', 'Логічних ядер', 'X_1(G), оп/с', 'X_1(RW), оп/с', 'Інваріанти'],
              [[9, 5, 4, machine['python'].split()[0] + ' / ' + machine['implementation'],
                machine['logical_cpus'], serial_g['X'], serial_rw['X'], 'Виконано']]),
        'X_1 виміряно окремо для кожного замка: один потік повторює цикл '
        'з п’яти записів і чотирьох читань. Час критичної секції для запису '
        'і читання виміряно в цьому однопотоковому режимі без конкуренції.',
        '## 2. Глобальний замок',
        'Усі операції утримують один threading.Lock протягом усього доступу до списку.',
    ]
    fields = ('N', 'X', 'p50_us', 'p99_us', 'wait_max_ms', 'w', 'cv')
    for title, item, extra in [('Таблиця 2. Глобальний замок', g, True), ('Таблиця 3. RWLock', rw, False)]:
        if not extra:
            text += ['## 3. RWLock',
                     'RWLock реалізовано через threading.Condition і м’ютекс. '
                     'Активний писець виключає всіх інших. Читачі можуть працювати разом, '
                     'якщо їхні послідовні заявки стоять перед наступним писцем. '
                     'Політика FIFO реалізована лічильниками квитків без готової черги: '
                     'наступна заявка допускається за номером; писець чекає виходу всіх читачів. '
                     'Нові читачі не обходять писця, який уже очікує. Порядок діє від моменту отримання квитка. '
                     'contains і size не змінюють вузлів, лічильників або порядку списку.']
        headers = ['Роль', 'Операцій за D', 'X, оп/с', 'p50, мкс', 'p99, мкс', 'max t_wait, мс', 'w', 'cv']
        rows = [[label] + [item['roles'][role][f] for f in fields]
                for label, role in [('Запис', 'write'), ('Читання', 'read')]]
        if extra:
            headers.append('t_cs, мкс')
            rows[0].append(csw)
            rows[1].append(csr)
        rows.append(['Разом', median(sum(r['roles'][x]['N'] for x in ('write', 'read')) for r in full if r['mode'] == ('global' if extra else 'rw') and r['kind'] == 'parallel'),
                     item['X']] + ['—'] * (len(headers) - 3))
        text += ['### ' + title, table(headers, rows)]
    text += ['### Таблиця 4. Операції потоків за D секунд',
             table(['Потік', 'Роль', 'Глобальний замок', 'RWLock'],
                   [[i+1, 'запис' if i % 2 == 0 else 'читання', g['threads'][i], rw['threads'][i]] for i in range(9)]),
             '## 4. Прискорення та межа пропускної здатності',
             '### Таблиця 5. Метрики прискорення',
             table(['Метрика', 'Формула', 'Значення'], [
                 ['S(n), G', 'X(G) / X_1(G)', metrics['S_global']],
                 ['E(n), G', 'S(n,G) / 9', metrics['E_global']],
                 ['S(n), RW', 'X(RW) / X_1(RW)', metrics['S_rw']],
                 ['E(n), RW', 'S(n,RW) / 9', metrics['E_rw']],
                 ['S_w', 'X_w(RW) / X_w(G)', metrics['S_w']],
                 ['S_r', 'X_r(RW) / X_r(G)', metrics['S_r']],
                 ['S_Σ', 'X(RW) / X(G)', metrics['S_total']],
                 ['ρ', 'X(G) · t̄_cs', metrics['rho']]]),
             f't̄_cs = (5 · {csw:.6g} + 4 · {csr:.6g}) / 9 = {cs*1e6:.6g} мкс. '
             f'Межа 1 / t̄_cs = {limit:.6g} оп/с; виміряне X(G) = {g["X"]:.6g} оп/с.',
             'Межа за методикою є оцінкою: ваги 5:4 описують кількість потоків, '
             'а фактичне співвідношення завершених операцій може відрізнятися. '
             'На оцінку також впливають витрати вимірювання і зміна часу секції під конкуренцією.',
             '## 5. Порівняння доступу до даних',
             '### Таблиця 6. Порівняння доступу до даних']
    comparison = []
    for label, key in [('X, оп/с','X'), ('x на потік, оп/с','x'), ('p50, мкс','p50_us'),
                       ('p99, мкс','p99_us'), ('h = p99 / p50','h'),
                       ('max t_wait, мс','wait_max_ms'), ('w','w'), ('cv','cv'), ('φ','phi')]:
        vals = [v['roles'][r][key] for v in (g,rw) for r in ('write','read')]
        ratios = [vals[2+i] / vals[i] if vals[i] else f'Δ={vals[2+i]-vals[i]:.6g}' for i in range(2)]
        comparison.append([label] + vals + ratios)
    text += [table(['Показник','G: запис','G: читання','RW: запис','RW: читання','RW/G: запис','RW/G: читання'],comparison)]
    for role, label, ratio in [('write','запису',metrics['S_w']), ('read','читання',metrics['S_r'])]:
        a,b=g['roles'][role],rw['roles'][role]
        text.append(f'Для {label} відношення швидкостей RW/G становить {ratio:.4g}: '
                    f'швидкість {"зросла" if ratio>1 else "зменшилася" if ratio<1 else "не змінилася"}. '
                    f'Частка очікування змінилася з {a["w"]:.4g} до {b["w"]:.4g}, '
                    f'відношення хвоста h — з {a["h"]:.4g} до {b["h"]:.4g}, '
                    f'cv — з {a["cv"]:.4g} до {b["cv"]:.4g}. '
                    'Ці значення характеризують очікування замка, довгі операції та нерівномірність доступу відповідно.')
    text += ['## Перевірка коректності',
             'Після кожного прогону перевірено відсутність циклів, діапазон ключів, '
             'строге зростання без повторень і збіг size з кількістю вузлів. '
             'Розмір додатково звірено з початковими 512 вузлами та сумою успішних add/remove '
             'в усіх потоках, включно з прогрівом. Усі contains звірено з отриманим набором ключів; '
             'повторний обхід підтвердив, що читання не змінює структуру.',
             '## Висновок',
             f'Сумарне відношення пропускної здатності RW/G: {metrics["S_total"]:.4g}. '
             'Спільний режим читання сам по собі не гарантує прискорення: '
             'важливі тривалість обходу, конкуренція з писцями та витрати синхронізації.',
             f'Середовище: {machine["platform"]}. GIL увімкнений: {machine["gil_enabled"]}. '
             'У звичайному CPython GIL обмежує паралельне виконання Python-коду. '
             'Тому вимірювання характеризують саме цей стенд і не доводять загальної переваги одного типу замка.',
             '## Відтворення',
             'Запуск: python benchmark.py. Перебудова таблиць: python report.py results/<каталог>. '
             'machine.json містить параметри машини; JSON прогонів — метрики і кількість операцій потоків; '
             'bin.gz — усі індивідуальні тривалості. Файл формату описано в README.md.',
             'Джерело: методичні вказівки до лабораторної роботи 5; '
             'https://docs.python.org/3/library/threading.html']
    if machine['smoke']:
        text.insert(1, '**ТЕХНІЧНА ПЕРЕВІРКА. Скорочені виміри, не результати лабораторної роботи.**')
    (directory / 'REPORT.md').write_text('\n\n'.join(text) + '\n', encoding='utf-8')
    (directory / 'summary.json').write_text(json.dumps(dict(metrics=metrics,
        critical_section_us=dict(write=csw,read=csr,weighted=cs*1e6),limit=limit),indent=2), encoding='utf-8')
    with (directory / 'runs.csv').open('w', encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['mode','kind','repeat','role','N','X','p50_us','p99_us','wait_max_ms','w','cv','t_cs_us'])
        for r in full:
            for role in ('write','read'):
                writer.writerow([r['mode'],r['kind'],r['repeat'],role]+[r['roles'][role][k] for k in ('N','X','p50_us','p99_us','wait_max_ms','w','cv','t_cs_us')])
    print('REPORT.md, summary.json, runs.csv saved.',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    build(parser.parse_args().directory)
