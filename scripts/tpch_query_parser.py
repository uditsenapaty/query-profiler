#tpch_query_parser.py
import re
from sqlglot import parse_one, exp


class TPCHQueryParser:

    def clean_sql(self, sql):

        sql = re.sub(r"--.*", "", sql)

        sql = sql.strip()

        if sql.endswith(";"):
            sql = sql[:-1]

        return sql

    def parse(self, sql):

        sql = self.clean_sql(sql)

        tree = parse_one(sql, read="postgres")

        return {
            "aliases": self.extract_aliases(tree),
            "parameters": self.extract_parameters(tree),
            "predicates": self.extract_predicates(tree),
        }

    # =====================================================
    # aliases
    # =====================================================

    def extract_aliases(self, tree):

        aliases = {}

        for table in tree.find_all(exp.Table):

            alias = table.alias

            if alias:
                aliases[alias] = table.name
            else:
                aliases[table.name] = table.name

        return aliases

    # =====================================================
    # parameters
    # =====================================================

    def extract_parameters(self, tree):

        params = []

        for node in tree.walk():

            if isinstance(node, exp.Placeholder):
                params.append(node.sql())

        return sorted(list(set(params)))

    # =====================================================
    # predicates
    # =====================================================

    def extract_predicates(self, tree):

        predicates = []

        predicate_types = (
            exp.EQ,
            exp.NEQ,
            exp.GT,
            exp.GTE,
            exp.LT,
            exp.LTE,
            exp.Like,
            exp.ILike,
            exp.In,
            exp.Between,
        )

        for node in tree.walk():

            if isinstance(node, predicate_types):

                predicates.append({
                    "type": type(node).__name__,
                    "sql": node.sql(),
                    "columns": self.extract_expr_columns(node),
                    "parameters": self.extract_expr_parameters(node),
                })

            elif isinstance(node, exp.Exists):

                predicates.append({
                    "type": "EXISTS",
                    "sql": node.sql(),
                    "columns": self.extract_expr_columns(node),
                    "parameters": self.extract_expr_parameters(node),
                })

            elif isinstance(node, exp.Not):

                if isinstance(node.this, exp.Exists):

                    predicates.append({
                        "type": "NOT EXISTS",
                        "sql": node.sql(),
                        "columns": self.extract_expr_columns(node),
                        "parameters": self.extract_expr_parameters(node),
                    })

        return predicates

    # =====================================================
    # helper
    # =====================================================

    def extract_expr_columns(self, expr):

        cols = []

        for col in expr.find_all(exp.Column):
            cols.append(col.sql())

        return sorted(list(set(cols)))

    def extract_expr_parameters(self, expr):

        params = []

        for node in expr.walk():

            if isinstance(node, exp.Placeholder):
                params.append(node.sql())

        return sorted(list(set(params)))