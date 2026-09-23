"""Плата и ревизия по номеру — найти или завести, и сохранить состав из BOM.

Вынесено из представлений: тем же путём приходят и загрузка BOM на сайте,
и импорт карточек Confluence (``manage.py import_cards``). Раньше каждый
из них искал плату и ревизию по-своему — точным совпадением, без учёта
регистра, сравнением match_key в питоне, — и одна и та же плата, пришедшая
двумя путями, в реестре задваивалась. Правило теперь одно:
``Board.objects.by_number`` и ``Board.revision_by_number``.
"""

from django.db import transaction

from servers.boards_bridge import sync_board

from .models import Board, BoardItem, BoardRevision
from .revisions import parse_pn


def board_for(base_pn):
    """Плата с этим номером или новая, ещё не сохранённая.

    Найденную не переименовываем: номер у неё уже записан так, как его
    ведут, а другое написание в файле («hsbp-5s01») — не повод его менять.
    """
    return Board.objects.by_number(base_pn) or Board(base_pn=base_pn)


def revision_for(board, oy_pn):
    """Ревизия платы с этим номером или новая, со следующим номером.

    Новая не сохраняется: что в неё записать до сохранения, решает
    вызывающий. Плата должна быть уже сохранена — номер ревизии считается
    по её ревизиям.
    """
    revision = board.revision_by_number(oy_pn)
    if revision is None:
        revision = BoardRevision(board=board,
                                 number=board.next_revision_number())
        revision.apply_pn(oy_pn)
    return revision


@transaction.atomic
def store_revision(header, items, username):
    """Сохраняет разобранный BOM: плату, ревизию и её состав.

    Плата опознаётся по базовому номеру, ревизия — по полному: HSBP-5S01-02C
    и HSBP-5S01-02D это две ревизии одной платы, а не две платы. Повторная
    загрузка того же номера обновляет свою ревизию, а не плодит копии.

    Имя файла сюда больше не передаётся: хранить его перестали — одно и то
    же «BOM.xlsx» у десятка ревизий ничего не опознавало.
    """
    full_pn = header["oy_pn"]
    base_pn, _, _ = parse_pn(full_pn)

    board = board_for(base_pn)
    # шапка BOM у платы не хранится: она своя у каждой ревизии
    board.imported_by = username
    board.save()

    revision = revision_for(board, full_pn)
    # У найденной ревизии номер остаётся своим, но разобранные из него поля
    # пересчитываются: правило разбора могло поменяться с прошлой загрузки
    revision.apply_pn(revision.oy_pn)
    revision.apply_header(header)
    # отметка ставится при каждой загрузке: спрашивают «когда состав
    # обновляли», а не «когда ревизия появилась»
    revision.remember_source(username)
    revision.save()
    # состав ревизии заменяется целиком: файл — источник истины
    revision.items.all().delete()
    BoardItem.objects.bulk_create(
        [BoardItem(revision=revision, **item) for item in items], batch_size=500)

    board.set_current(revision)
    # у платы должна быть позиция: в составе изделия она участвует как
    # позиция, а заводить её отдельной командой после каждого импорта —
    # лишний шаг, о котором забудут
    sync_board(board)
    return revision
