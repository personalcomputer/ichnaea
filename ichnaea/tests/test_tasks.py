from datetime import datetime
from datetime import timedelta
from hashlib import sha1

from sqlalchemy.orm.exc import FlushError

from ichnaea.db import (
    CellMeasure,
    Measure,
    Stat,
    STAT_TYPE,
    WifiMeasure,
)
from ichnaea.tasks import DatabaseTask
from ichnaea.tests.base import CeleryTestCase
from ichnaea.worker import celery


@celery.task(base=DatabaseTask)
def add_measure(lat=0, lon=0, fail_counter=None, fails=10):
    try:
        if fail_counter:
            fail_counter[0] += 1
        with add_measure.db_session() as session:
            measure = Measure(lat=lat, lon=lon)
            session.add(measure)
            if fail_counter:
                session.flush()
                measure2 = Measure(lat=0, lon=0)
                # provoke error via duplicate id
                measure2.id = measure.id
                if fail_counter[0] < fails:
                    session.add(measure2)
            session.commit()
    except Exception as exc:
        raise add_measure.retry(exc=exc)


class TestTaskDatabaseIntegration(CeleryTestCase):

    def test_add_measure(self):
        result = add_measure.delay(lat=12345678, lon=23456789)
        self.assertTrue(result.get() is None)
        self.assertTrue(result.successful())

        session = self.db_master_session
        result = session.query(Measure).first()
        self.assertEqual(result.lat, 12345678)
        self.assertEqual(result.lon, 23456789)

    def test_add_measure_fail(self):
        counter = [0]
        self.assertRaises(
            FlushError, add_measure.delay, fail_counter=counter)
        self.assertEqual(counter[0], 4)

        session = self.db_master_session
        result = session.query(Measure).count()
        self.assertEqual(result, 0)

    def test_add_measure_retry(self):
        counter = [0]
        result = add_measure.delay(fail_counter=counter, fails=1)
        self.assertTrue(result.get() is None)
        self.assertEqual(counter[0], 1)

        session = self.db_master_session
        result = session.query(Measure).count()
        self.assertEqual(result, 1)


class TestStats(CeleryTestCase):

    def test_histogram(self):
        from ichnaea.tasks import histogram
        session = self.db_master_session
        today = datetime.utcnow().date()
        yesterday = (today - timedelta(1))
        two_days = (today - timedelta(2))
        long_ago = (today - timedelta(40))
        wifi = '[{"key": "a"}]'
        measures = [
            Measure(lat=10000000, lon=20000000, created=today, wifi=wifi),
            Measure(lat=10000000, lon=20000000, created=today, wifi=wifi),
            Measure(lat=10000000, lon=20000000, created=yesterday, wifi=wifi),
            Measure(lat=10000000, lon=20000000, created=two_days, wifi=wifi),
            Measure(lat=10000000, lon=20000000, created=two_days, wifi=wifi),
            Measure(lat=10000000, lon=20000000, created=two_days, wifi=wifi),
            Measure(lat=10000000, lon=20000000, created=long_ago, wifi=wifi),
        ]
        session.add_all(measures)
        session.commit()

        result = histogram.delay(start=30, end=0)
        added = result.get()
        self.assertEqual(added, 3)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 3)
        self.assertEqual(stats[0].key, STAT_TYPE['location'])
        self.assertEqual(stats[0].time, two_days)
        self.assertEqual(stats[1].time, yesterday)
        self.assertEqual(stats[2].time, today)
        self.assertEqual(stats[0].value, 3)
        self.assertEqual(stats[1].value, 1)
        self.assertEqual(stats[2].value, 2)

        # test older time range
        result = histogram.delay(start=60, end=30)
        added = result.get()
        self.assertEqual(added, 1)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 4)
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)

        # test duplicate execution
        result = histogram.delay()
        added = result.get()
        self.assertEqual(added, 0)

    def test_cell_histogram(self):
        from ichnaea.tasks import cell_histogram
        session = self.db_master_session
        today = datetime.utcnow().date()
        yesterday = (today - timedelta(1))
        two_days = (today - timedelta(2))
        long_ago = (today - timedelta(40))
        measures = [
            CellMeasure(lat=10000000, lon=20000000, created=today),
            CellMeasure(lat=10000000, lon=20000000, created=today),
            CellMeasure(lat=10000000, lon=20000000, created=yesterday),
            CellMeasure(lat=10000000, lon=20000000, created=two_days),
            CellMeasure(lat=10000000, lon=20000000, created=two_days),
            CellMeasure(lat=10000000, lon=20000000, created=two_days),
            CellMeasure(lat=10000000, lon=20000000, created=long_ago),
        ]
        session.add_all(measures)
        session.commit()

        result = cell_histogram.delay(start=30, end=0)
        added = result.get()
        self.assertEqual(added, 3)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 3)
        self.assertEqual(stats[0].key, STAT_TYPE['cell'])
        self.assertEqual(stats[0].time, two_days)
        self.assertEqual(stats[1].time, yesterday)
        self.assertEqual(stats[2].time, today)
        self.assertEqual(stats[0].value, 3)
        self.assertEqual(stats[1].value, 1)
        self.assertEqual(stats[2].value, 2)

        # test older time range
        result = cell_histogram.delay(start=60, end=30)
        added = result.get()
        self.assertEqual(added, 1)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 4)
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)

        # test duplicate execution
        result = cell_histogram.delay()
        added = result.get()
        self.assertEqual(added, 0)

    def test_unique_cell_histogram(self):
        from ichnaea.tasks import unique_cell_histogram
        session = self.db_master_session
        today = datetime.utcnow().date()
        one_day = (today - timedelta(1))
        two_days = (today - timedelta(2))
        long_ago = (today - timedelta(40))
        measures = [
            CellMeasure(created=long_ago, radio=0, mcc=1, mnc=2, lac=3, cid=4),
            CellMeasure(created=two_days, radio=2, mcc=1, mnc=2, lac=3, cid=4),
            CellMeasure(created=two_days, radio=0, mcc=1, mnc=2, lac=3, cid=4),
            CellMeasure(created=two_days, radio=0, mcc=2, mnc=2, lac=3, cid=4),
            CellMeasure(created=one_day, radio=0, mcc=2, mnc=2, lac=3, cid=5),
            CellMeasure(created=today, radio=0, mcc=1, mnc=3, lac=3, cid=4),
            CellMeasure(created=today, radio=0, mcc=1, mnc=2, lac=4, cid=4),
        ]
        session.add_all(measures)
        session.commit()

        result = unique_cell_histogram.delay(ago=40)
        self.assertEqual(result.get(), 1)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].key, STAT_TYPE['unique_cell'])
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)

        # fill up newer dates
        unique_cell_histogram.delay(ago=2).get()
        unique_cell_histogram.delay(ago=1).get()
        unique_cell_histogram.delay(ago=0).get()

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 4)
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)
        self.assertEqual(stats[1].time, two_days)
        self.assertEqual(stats[1].value, 3)
        self.assertEqual(stats[2].time, one_day)
        self.assertEqual(stats[2].value, 4)
        self.assertEqual(stats[3].time, today)
        self.assertEqual(stats[3].value, 6)

        # test duplicate execution
        result = unique_cell_histogram.delay()
        self.assertEqual(result.get(), 0)

    def test_wifi_histogram(self):
        from ichnaea.tasks import wifi_histogram
        session = self.db_master_session
        today = datetime.utcnow().date()
        yesterday = (today - timedelta(1))
        two_days = (today - timedelta(2))
        long_ago = (today - timedelta(40))
        measures = [
            WifiMeasure(lat=10000000, lon=20000000, created=today),
            WifiMeasure(lat=10000000, lon=20000000, created=today),
            WifiMeasure(lat=10000000, lon=20000000, created=yesterday),
            WifiMeasure(lat=10000000, lon=20000000, created=two_days),
            WifiMeasure(lat=10000000, lon=20000000, created=two_days),
            WifiMeasure(lat=10000000, lon=20000000, created=two_days),
            WifiMeasure(lat=10000000, lon=20000000, created=long_ago),
        ]
        session.add_all(measures)
        session.commit()

        result = wifi_histogram.delay(start=30, end=0)
        added = result.get()
        self.assertEqual(added, 3)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 3)
        self.assertEqual(stats[0].key, STAT_TYPE['wifi'])
        self.assertEqual(stats[0].time, two_days)
        self.assertEqual(stats[1].time, yesterday)
        self.assertEqual(stats[2].time, today)
        self.assertEqual(stats[0].value, 3)
        self.assertEqual(stats[1].value, 1)
        self.assertEqual(stats[2].value, 2)

        # test older time range
        result = wifi_histogram.delay(start=60, end=30)
        added = result.get()
        self.assertEqual(added, 1)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 4)
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)

        # test duplicate execution
        result = wifi_histogram.delay()
        added = result.get()
        self.assertEqual(added, 0)

    def test_unique_wifi_histogram(self):
        from ichnaea.tasks import unique_wifi_histogram
        session = self.db_master_session
        today = datetime.utcnow().date()
        yesterday = (today - timedelta(1))
        two_days = (today - timedelta(2))
        long_ago = (today - timedelta(40))
        k1 = sha1('1').hexdigest()
        k2 = sha1('2').hexdigest()
        k3 = sha1('3').hexdigest()
        measures = [
            WifiMeasure(lat=10000000, lon=20000000, created=long_ago, key=k1),
            WifiMeasure(lat=10000000, lon=20000000, created=two_days, key=k1),
            WifiMeasure(lat=10000000, lon=20000000, created=two_days, key=k2),
            WifiMeasure(lat=10000000, lon=20000000, created=two_days, key=k1),
            WifiMeasure(lat=10000000, lon=20000000, created=yesterday, key=k3),
            WifiMeasure(lat=10000000, lon=20000000, created=today, key=k2),
            WifiMeasure(lat=10000000, lon=20000000, created=today, key=k3),
        ]
        session.add_all(measures)
        session.commit()

        result = unique_wifi_histogram.delay(ago=40)
        added = result.get()
        self.assertEqual(added, 1)

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].key, STAT_TYPE['unique_wifi'])
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)

        # fill up newer dates
        unique_wifi_histogram.delay(ago=2).get()
        unique_wifi_histogram.delay(ago=1).get()
        unique_wifi_histogram.delay(ago=0).get()

        stats = session.query(Stat).order_by(Stat.time).all()
        self.assertEqual(len(stats), 4)
        self.assertEqual(stats[0].time, long_ago)
        self.assertEqual(stats[0].value, 1)
        self.assertEqual(stats[1].time, two_days)
        self.assertEqual(stats[1].value, 2)
        self.assertEqual(stats[2].time, yesterday)
        self.assertEqual(stats[2].value, 3)
        self.assertEqual(stats[3].time, today)
        self.assertEqual(stats[3].value, 3)

        # test duplicate execution
        result = unique_wifi_histogram.delay()
        self.assertEqual(result.get(), 0)
