"""Explicit in-memory defective baselines. Never patch the working tree.

Each mutation must match exactly one known AST node or refuse to run. The lab
proves its oracles notice the defect, not that these mutants represent all bugs.
"""
import ast
import copy
import hashlib
import inspect


def mutated(function, kind):
    tree = ast.parse(inspect.getsource(function))
    changes = 0

    class Mutation(ast.NodeTransformer):
        def visit_If(self, node):
            nonlocal changes
            self.generic_visit(node)
            expression = ast.unparse(node.test)
            matches = {
                "late_fence": "request.current_attempt_id != attempt.id" in expression,
                "snapshot_fence": "fresh['snapshot_hash'] != proposal.preview_hash" == expression,
                "accepted_redelivery": expression == "attempt.state == 'accepted'",
            }
            if matches.get(kind, False):
                node.test = ast.Constant(False)
                changes += 1
            return node

        def visit_Call(self, node):
            nonlocal changes
            self.generic_visit(node)
            if kind == "tenant_scope" and isinstance(node.func, ast.Attribute) and node.func.attr == "where":
                keep = [arg for arg in node.args if "model.tenant_id == tenant_id" != ast.unparse(arg)]
                if len(keep) != len(node.args):
                    changes += len(node.args) - len(keep)
                    node.args = keep
            return node

        def visit_Expr(self, node):
            nonlocal changes
            if kind == "outbox" and ast.unparse(node).startswith("db.add(Outbox("):
                changes += 1
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)

    tree = ast.fix_missing_locations(Mutation().visit(copy.deepcopy(tree)))
    if changes != 1:
        raise ValueError(f"Mutation {kind} requires exactly one known node; matched {changes}")
    namespace = dict(function.__globals__)
    exec(compile(tree, f"<ownstack-lab-only:{kind}>", "exec"), namespace)
    result = namespace[function.__name__]
    return result, hashlib.sha256(ast.unparse(tree).encode()).hexdigest()
